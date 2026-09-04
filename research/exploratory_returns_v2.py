"""Pure failed-break v2 exploratory return calculations.

This module has no Django, ORM, filesystem, process, provider, or network path.
It consumes already-normalized sealed evidence. Persistent execution remains a
separate, unauthorized operation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from functools import wraps
from statistics import median
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DECIMAL_CONTEXT = Context(prec=38, rounding=ROUND_HALF_EVEN)
MONEY_QUANTUM = Decimal("0.0000000001")
R_QUANTUM = Decimal("0.0000000001")
COMMISSIONS = (Decimal("0"), Decimal("0.5"), Decimal("1"))
FINANCING_RATES = (
    Decimal("-0.06"),
    Decimal("-0.03"),
    Decimal("0"),
    Decimal("0.03"),
    Decimal("0.06"),
)
RISK_LEVELS = (Decimal("25"), Decimal("50"), Decimal("100"))
GEOMETRY_SIGMA_GRID = (Decimal("0.5"), Decimal("1.0"), Decimal("1.5"))
SENSITIVITY_SIGMA_GRID = (Decimal("0.5"), Decimal("1.0"), Decimal("2.0"))
TERMINALS = ("STOP", "TARGET", "DAILY_STRUCTURE", "HORIZON", "UNRESOLVED_DATA")
EVENT_FIELDS = {
    "physical_event_key",
    "books",
    "instrument",
    "direction",
    "entry_at",
    "horizon_at",
    "entry_bid",
    "entry_ask",
    "stop",
    "target",
    "supporting_swing",
    "pip_size",
    "risk_per_unit_cad",
    "expected_h1_starts",
    "d_completions",
    "h1",
    "daily",
    "conversion",
    "rollovers",
    "marks",
}
H1_FIELDS = {
    "start",
    "sealed",
    "complete",
    "conflict",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
}
DAILY_FIELDS = {"completed_at", "sealed", "complete", "conflict", "mid_close"}
CONVERSION_FIELDS = {"currency", "as_of", "legs"}
LEG_FIELDS = {
    "pair",
    "direction",
    "completed_at",
    "midpoint_close",
    "sealed",
    "complete",
    "conflict",
}
ROLLOVER_FIELDS = {"at", "multiplier", "midpoint", "conversion"}
MARK_FIELDS = {"at", "side_close", "conversion"}
CAD_ROUTES = {
    "CAD": (),
    "USD": (("USD_CAD", "multiply"),),
    "GBP": (("GBP_USD", "multiply"), ("USD_CAD", "multiply")),
    "JPY": (("USD_JPY", "divide"), ("USD_CAD", "multiply")),
}


class ReturnRefusal(ValueError):
    """Malformed, incomplete, or unauthorized calculation input."""


def governed_decimal(function):
    """Run each independently callable calculation under the frozen context."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(DECIMAL_CONTEXT):
            return function(*args, **kwargs)

    return wrapped


def require(condition, message):
    if not condition:
        raise ReturnRefusal(message)


def decimal(value) -> Decimal:
    require(not isinstance(value, float), "binary float is prohibited")
    try:
        return Decimal(str(value))
    except Exception as error:  # Decimal raises several value/type subclasses.
        raise ReturnRefusal("invalid decimal") from error


def timestamp(value) -> datetime:
    require(isinstance(value, str), "timestamp must be canonical text")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReturnRefusal("invalid timestamp") from error
    require(result.tzinfo is not None, "timestamp must be timezone-aware")
    return result.astimezone(UTC)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def rendered(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def ratio(value: Decimal) -> Decimal:
    return value.quantize(R_QUANTUM, rounding=ROUND_HALF_EVEN)


def _exact_fields(row: dict, fields: set[str], label: str):
    require(isinstance(row, dict) and set(row) == fields, f"unexpected {label} field")


def _pair_quote(instrument: str) -> str:
    parts = instrument.split("_")
    require(len(parts) == 2 and all(parts), "invalid instrument")
    return parts[1]


@governed_decimal
def conversion_rate(evidence: dict, currency: str, as_of: datetime) -> Decimal:
    """Resolve the fixed CAD route from strictly prior sealed midpoint evidence."""
    _exact_fields(evidence, CONVERSION_FIELDS, "conversion")
    require(evidence["currency"] == currency, "conversion currency mismatch")
    require(timestamp(evidence["as_of"]) == as_of, "conversion decision-time mismatch")
    expected = CAD_ROUTES.get(currency)
    require(expected is not None, "unsupported CAD conversion currency")
    legs = evidence["legs"]
    require(len(legs) == len(expected), "conversion route length mismatch")
    rate = Decimal(1)
    for leg, (pair, direction) in zip(legs, expected, strict=True):
        _exact_fields(leg, LEG_FIELDS, "conversion leg")
        require(
            leg["pair"] == pair and leg["direction"] == direction,
            "conversion route substitution",
        )
        require(
            leg["sealed"] is True and leg["complete"] is True and leg["conflict"] is False,
            "missing or conflicting sealed conversion evidence",
        )
        require(timestamp(leg["completed_at"]) < as_of, "conversion evidence is not strictly prior")
        midpoint = decimal(leg["midpoint_close"])
        require(midpoint > 0, "non-positive conversion midpoint")
        rate = rate * midpoint if direction == "multiply" else rate / midpoint
    return rate


def _validate_bar(row: dict) -> dict:
    _exact_fields(row, H1_FIELDS, "H1")
    require(
        row["sealed"] is True and row["complete"] is True and row["conflict"] is False,
        "missing or conflicting expected H1 member",
    )
    result = {"start": timestamp(row["start"])}
    for field in H1_FIELDS - {"start", "sealed", "complete", "conflict"}:
        result[field] = decimal(row[field])
    require(
        result["bid_low"] <= result["bid_open"] <= result["bid_high"]
        and result["ask_low"] <= result["ask_open"] <= result["ask_high"],
        "invalid H1 OHLC",
    )
    require(
        result["bid_open"] <= result["ask_open"] and result["bid_close"] <= result["ask_close"],
        "crossed side-aware H1 price",
    )
    return result


def _structure_due(event: dict, entry_at: datetime, boundary: datetime) -> bool:
    direction = event["direction"]
    swing = decimal(event["supporting_swing"])
    rows = {timestamp(row["completed_at"]): row for row in event["daily"]}
    require(len(rows) == len(event["daily"]), "duplicate daily member")
    completions = [
        timestamp(value)
        for value in event["d_completions"]
        if entry_at < timestamp(value) <= boundary
    ]
    for completed in completions:
        row = rows.get(completed)
        require(row is not None, "missing expected daily member")
        _exact_fields(row, DAILY_FIELDS, "daily")
        require(
            row["sealed"] is True and row["complete"] is True and row["conflict"] is False,
            "missing or conflicting expected daily member",
        )
        close = decimal(row["mid_close"])
        if completed > entry_at and (
            (direction == "long" and close < swing) or (direction == "short" and close > swing)
        ):
            return True
    return False


def _exit_conversion(event: dict, when: datetime) -> Decimal:
    quote = _pair_quote(event["instrument"])
    key = stamp(when)
    evidence = event["conversion"].get(key)
    require(evidence is not None, "missing point-in-time CAD conversion evidence")
    return conversion_rate(evidence, quote, when)


def _event_input(event: dict) -> tuple[datetime, datetime, tuple[dict, ...], tuple[datetime, ...]]:
    _exact_fields(event, EVENT_FIELDS, "event")
    require(isinstance(event["physical_event_key"], str) and event["physical_event_key"], "bad key")
    require(
        isinstance(event["books"], list)
        and event["books"] == sorted(set(event["books"]))
        and event["books"],
        "books must be nonempty unique classifications",
    )
    require(event["direction"] in {"long", "short"}, "invalid direction")
    entry_at, horizon_at = timestamp(event["entry_at"]), timestamp(event["horizon_at"])
    require(entry_at < horizon_at, "invalid horizon")
    starts = tuple(timestamp(value) for value in event["expected_h1_starts"])
    require(
        starts == tuple(sorted(set(starts))) and starts and starts[0] == entry_at,
        "bad H1 inventory",
    )
    require(horizon_at in starts, "horizon is not a sealed H1 successor")
    d_completions = tuple(timestamp(value) for value in event["d_completions"])
    require(
        len(d_completions) >= 10
        and d_completions == tuple(sorted(set(d_completions)))
        and all(value > entry_at for value in d_completions),
        "invalid sealed provider-D completion inventory",
    )
    derived_horizon = next((start for start in starts if start >= d_completions[9]), None)
    require(derived_horizon == horizon_at, "ten-provider-D-session horizon drift")
    bars = tuple(_validate_bar(row) for row in event["h1"])
    bar_starts = tuple(row["start"] for row in bars)
    require(bar_starts == starts, "expected H1 member missing, duplicated, or extra")
    return entry_at, horizon_at, bars, starts


@governed_decimal
def resolve_event(event: dict) -> dict:
    """Resolve one event under the complete H1 stop-first primary adapter."""
    try:
        entry_at, horizon_at, bars, starts = _event_input(event)
        direction = event["direction"]
        entry_bid, entry_ask = decimal(event["entry_bid"]), decimal(event["entry_ask"])
        stop, target = decimal(event["stop"]), decimal(event["target"])
        entry = entry_ask if direction == "long" else entry_bid
        require(
            bars[0]["bid_open"] == entry_bid and bars[0]["ask_open"] == entry_ask,
            "entry fill drift",
        )
        require(
            (direction == "long" and stop < entry < target)
            or (direction == "short" and target < entry < stop),
            "invalid frozen stop/target geometry",
        )
        require(
            (direction == "long" and entry_bid > stop)
            or (direction == "short" and entry_ask < stop),
            "entry open is an adverse-stop MISSED_FILL, not an eligible event",
        )
        terminal = exit_at = exit_price = None
        ambiguity = False
        for index, bar in enumerate(bars):
            structure_due = index and _structure_due(event, entry_at, bar["start"])
            if index and (structure_due or bar["start"] == horizon_at):
                terminal = "DAILY_STRUCTURE" if structure_due else "HORIZON"
                exit_at = bar["start"]
                exit_price = bar["bid_open"] if direction == "long" else bar["ask_open"]
                break
            if direction == "long":
                stop_touch, target_touch = bar["bid_low"] <= stop, bar["bid_high"] >= target
                adverse_open = bar["bid_open"]
                stop_fill = min(stop, adverse_open)
            else:
                stop_touch, target_touch = bar["ask_high"] >= stop, bar["ask_low"] <= target
                adverse_open = bar["ask_open"]
                stop_fill = max(stop, adverse_open)
            ambiguity = ambiguity or (stop_touch and target_touch)
            if stop_touch:
                terminal, exit_at, exit_price = "STOP", bar["start"] + timedelta(hours=1), stop_fill
                break
            if target_touch:
                terminal, exit_at, exit_price = "TARGET", bar["start"] + timedelta(hours=1), target
                break
        require(terminal is not None, "complete horizon did not resolve")
        exit_conversion = _exit_conversion(event, exit_at)
        risk_per_unit = decimal(event["risk_per_unit_cad"])
        require(risk_per_unit > 0, "invalid initial CAD risk")
        signed_quote = (exit_price - entry) * (1 if direction == "long" else -1)
        gross_cad_per_unit = signed_quote * exit_conversion
        gross_r = gross_cad_per_unit / risk_per_unit
        result = {
            "ambiguity": ambiguity,
            "books": event["books"],
            "direction": direction,
            "entry_at": stamp(entry_at),
            "entry_price": rendered(entry),
            "exit_at": stamp(exit_at),
            "exit_conversion_cad_per_quote": rendered(exit_conversion),
            "exit_price": rendered(exit_price),
            "gross_cad_per_unit": rendered(money(gross_cad_per_unit)),
            "gross_R": rendered(ratio(gross_r)),
            "instrument": event["instrument"],
            "observed_spread_effect": {
                "additional_subtraction": "0",
                "classification": "EMBEDDED_IN_SIDE_AWARE_ENTRY_AND_EXIT",
            },
            "physical_event_key": event["physical_event_key"],
            "risk_per_unit_cad": rendered(risk_per_unit),
            "terminal": terminal,
        }
        result["result_sha256"] = digest(result)
        return result
    except ReturnRefusal as error:
        return {
            "books": event.get("books", []),
            "physical_event_key": event.get("physical_event_key", "UNKNOWN"),
            "reason": str(error),
            "terminal": "UNRESOLVED_DATA",
        }


def _rollover_times(entry_at: datetime, exit_at: datetime) -> list[tuple[datetime, int]]:
    day = entry_at.astimezone(NY).replace(hour=17, minute=0, second=0, microsecond=0)
    if day.astimezone(UTC) <= entry_at:
        day += timedelta(days=1)
    result = []
    while day.astimezone(UTC) <= exit_at:
        if day.weekday() in {0, 1, 2, 3, 4}:
            result.append((day.astimezone(UTC), 3 if day.weekday() == 2 else 1))
        day += timedelta(days=1)
    return result


def _rollover_effect(
    event: dict,
    resolution: dict,
    units: Decimal,
    annual_rate: Decimal,
    initial_risk: Decimal,
) -> Decimal:
    total = Decimal(0)
    quote = _pair_quote(event["instrument"])
    expected = _rollover_times(timestamp(event["entry_at"]), timestamp(resolution["exit_at"]))
    require(len(event["rollovers"]) == len(expected), "missing or extra governed rollover")
    for row, (expected_at, expected_multiplier) in zip(event["rollovers"], expected, strict=True):
        _exact_fields(row, ROLLOVER_FIELDS, "rollover")
        when = timestamp(row["at"])
        multiplier = int(row["multiplier"])
        require(
            when == expected_at and multiplier == expected_multiplier,
            "rollover timestamp or multiplier changed",
        )
        rate = conversion_rate(row["conversion"], quote, when)
        total += abs(units) * decimal(row["midpoint"]) * annual_rate * multiplier / 365 * rate
    return total / initial_risk


@governed_decimal
def cost_grid(event: dict, resolution: dict, risk_cad: Decimal) -> list[dict]:
    require(resolution["terminal"] != "UNRESOLVED_DATA", "unresolved event has no cost grid")
    risk_cad = decimal(risk_cad)
    risk_per_unit = decimal(event["risk_per_unit_cad"])
    units = risk_cad / risk_per_unit
    exit_conversion = decimal(resolution["exit_conversion_cad_per_quote"])
    commission_base = abs(units) * decimal(event["pip_size"]) * exit_conversion / risk_cad
    gross_r = decimal(resolution["gross_R"])
    cells = []
    for commission in COMMISSIONS:
        for financing in FINANCING_RATES:
            commission_r = commission_base * commission
            financing_r = _rollover_effect(event, resolution, units, financing, risk_cad)
            net_r = gross_r - commission_r + financing_r
            row = {
                "additional_slippage_R": "0",
                "annual_financing_rate": rendered(financing),
                "commission_R": rendered(ratio(-commission_r)),
                "commission_pips": rendered(commission),
                "financing_R": rendered(ratio(financing_r)),
                "gross_cad": rendered(money(gross_r * risk_cad)),
                "gross_R": rendered(ratio(gross_r)),
                "net_R": rendered(ratio(net_r)),
                "net_cad": rendered(money(net_r * risk_cad)),
                "risk_cad": rendered(risk_cad),
                "spread_effect_R": "EMBEDDED_NOT_DOUBLE_SUBTRACTED",
            }
            row["cell_sha256"] = digest(row)
            cells.append(row)
    require(len(cells) == 15, "cost grid is not 3x5")
    return cells


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / len(values) if values else None


def _streaks(values: list[Decimal]) -> tuple[int, int]:
    longest_win = longest_loss = win = loss = 0
    for value in values:
        if value > 0:
            win, loss = win + 1, 0
        elif value < 0:
            loss, win = loss + 1, 0
        else:
            win = loss = 0
        longest_win, longest_loss = max(longest_win, win), max(longest_loss, loss)
    return longest_win, longest_loss


@governed_decimal
def summary_metrics(values: list[Decimal]) -> dict:
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    total = sum(values, Decimal(0))
    win_streak, loss_streak = _streaks(values)
    payoff = _mean(wins) / abs(_mean(losses)) if wins and losses else None
    profit_factor = sum(wins, Decimal(0)) / abs(sum(losses, Decimal(0))) if losses else None
    return {
        "average_R": rendered(ratio(_mean(values))) if values else None,
        "expectancy_R": rendered(ratio(_mean(values))) if values else None,
        "loss_rate": rendered(ratio(Decimal(len(losses)) / len(values))) if values else None,
        "longest_losing_streak": loss_streak,
        "longest_winning_streak": win_streak,
        "median_R": rendered(ratio(median(values))) if values else None,
        "payoff_ratio": rendered(ratio(payoff)) if payoff is not None else None,
        "profit_factor": rendered(ratio(profit_factor)) if profit_factor is not None else None,
        "total_R": rendered(ratio(total)),
        "win_rate": rendered(ratio(Decimal(len(wins)) / len(values))) if values else None,
    }


def _calendar_marks() -> list[datetime]:
    day = datetime(2010, 1, 1, 17, tzinfo=NY)
    end = datetime(2018, 12, 31, 17, tzinfo=NY)
    result = []
    while day <= end:
        result.append(day.astimezone(UTC))
        day += timedelta(days=1)
    return result


def _event_mark_r(event: dict, resolution: dict, when: datetime) -> Decimal:
    by_time = {}
    for row in event["marks"]:
        _exact_fields(row, MARK_FIELDS, "equity mark")
        at = timestamp(row["at"])
        require(at not in by_time, "duplicate equity mark")
        by_time[at] = row
    row = by_time.get(when)
    require(row is not None, "missing governed daily equity mark")
    quote = _pair_quote(event["instrument"])
    conversion = conversion_rate(row["conversion"], quote, when)
    side_close = decimal(row["side_close"])
    entry = decimal(resolution["entry_price"])
    sign = Decimal(1) if event["direction"] == "long" else Decimal(-1)
    return sign * (side_close - entry) * conversion / decimal(event["risk_per_unit_cad"])


@governed_decimal
def daily_equity_series(
    events: list[dict], resolutions: list[dict], r_by_event: dict[str, Decimal], risk: Decimal
) -> list[dict]:
    """Primary side-aware daily equity at every 17:00 New York calendar mark."""
    result_by_key = {row["physical_event_key"]: row for row in resolutions}
    rows = []
    for when in _calendar_marks():
        pnl = Decimal(0)
        for event in events:
            result = result_by_key[event["physical_event_key"]]
            entry_at, exit_at = timestamp(event["entry_at"]), timestamp(result["exit_at"])
            if when < entry_at:
                continue
            if exit_at <= when:
                pnl += r_by_event[event["physical_event_key"]] * risk
            else:
                pnl += _event_mark_r(event, result, when) * risk
        equity = Decimal(10000) + pnl
        rows.append({"at": stamp(when), "equity_cad": rendered(money(equity))})
    return rows


@governed_decimal
def daily_performance(equity_rows: list[dict]) -> dict:
    equities = [decimal(row["equity_cad"]) for row in equity_rows]
    require(equities, "daily equity series empty")
    peak, maximum_drawdown = Decimal(10000), Decimal(0)
    returns = []
    previous = Decimal(10000)
    for equity in equities:
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, Decimal(1) - equity / peak)
        require(previous > 0, "daily return undefined after non-positive equity")
        returns.append(equity / previous - 1)
        previous = equity
    mean_return = _mean(returns)
    sample_sd = None
    if len(returns) >= 2:
        sample_sd = (
            sum((value - mean_return) ** 2 for value in returns) / (len(returns) - 1)
        ).sqrt()
    downside = (sum(min(value, Decimal(0)) ** 2 for value in returns) / len(returns)).sqrt()
    annualizer = Decimal("365.2425").sqrt()
    cumulative = equities[-1] / Decimal(10000) - 1
    return {
        "cumulative_return": rendered(ratio(cumulative)),
        "daily_return_count": len(returns),
        "maximum_drawdown_fraction": rendered(ratio(maximum_drawdown)),
        "sharpe_descriptive": (
            rendered(ratio(annualizer * mean_return / sample_sd))
            if sample_sd not in {None, Decimal(0)}
            else None
        ),
        "sortino_descriptive": (
            rendered(ratio(annualizer * mean_return / downside)) if downside else None
        ),
    }


def _month_keys() -> list[str]:
    return [f"{year:04d}-{month:02d}" for year in range(2010, 2019) for month in range(1, 13)]


@governed_decimal
def fixed_capital_diagnostic(
    events: list[dict],
    resolutions: list[dict],
    scenario_by_event: dict[str, Decimal],
    risk: Decimal,
) -> dict:
    """Non-compounding fixed-risk diagnostic with all 108 calendar months."""
    resolved = {row["physical_event_key"]: row for row in resolutions}
    monthly = {key: Decimal(0) for key in _month_keys()}
    annual = {str(year): Decimal(0) for year in range(2010, 2019)}
    entries = Counter()
    intervals = []
    ordered_pnl = []
    for event in sorted(events, key=lambda row: (row["entry_at"], row["physical_event_key"])):
        result = resolved[event["physical_event_key"]]
        require(result["terminal"] != "UNRESOLVED_DATA", "incomplete terminal set")
        pnl = scenario_by_event[event["physical_event_key"]] * risk
        exit_ny = timestamp(result["exit_at"]).astimezone(NY)
        key = f"{exit_ny.year:04d}-{exit_ny.month:02d}"
        require(key in monthly, "exit outside development period")
        monthly[key] += pnl
        annual[str(exit_ny.year)] += pnl
        entries[timestamp(event["entry_at"]).astimezone(NY).strftime("%Y-%m")] += 1
        intervals.append((timestamp(event["entry_at"]), timestamp(result["exit_at"])))
        ordered_pnl.append(pnl)
    daily = daily_equity_series(events, resolutions, scenario_by_event, risk)
    daily_stats = daily_performance(daily)
    equity = Decimal(10000)
    month_rows = []
    for key, pnl in monthly.items():
        equity += pnl
        month_rows.append(
            {"month": key, "pnl_cad": rendered(money(pnl)), "equity_cad": rendered(money(equity))}
        )
    changes = list(monthly.values())
    total_r = sum(scenario_by_event.values(), Decimal(0))
    peak_open = 0
    for start, _ in intervals:
        peak_open = max(peak_open, sum(1 for left, right in intervals if left <= start < right))
    max_dd = decimal(daily_stats["maximum_drawdown_fraction"]) * Decimal(10000)
    recovery = sum(ordered_pnl, Decimal(0)) / max_dd if max_dd > 0 else None
    inverse = {
        target: (Decimal(target) * 108 / total_r if total_r > 0 else None)
        for target in ("800", "1000")
    }
    return {
        "annual_pnl_cad": {key: rendered(money(value)) for key, value in annual.items()},
        "average_monthly_pnl_cad": rendered(money(sum(changes) / 108)),
        "best_month_cad": rendered(money(max(changes))),
        "ending_equity_cad": rendered(money(equity)),
        "daily_equity": daily,
        "daily_performance": daily_stats,
        "maximum_drawdown_R": rendered(ratio(max_dd / risk)),
        "maximum_drawdown_cad": rendered(money(max_dd)),
        "maximum_drawdown_fraction": rendered(ratio(max_dd / Decimal(10000))),
        "median_monthly_pnl_cad": rendered(money(median(changes))),
        "month_rows": month_rows,
        "months_at_or_above_1000": sum(value >= 1000 for value in changes),
        "months_at_or_above_800": sum(value >= 800 for value in changes),
        "months_with_entry": sum(bool(entries[key]) for key in monthly),
        "peak_aggregate_open_risk_cad": rendered(risk * peak_open),
        "positive_negative_zero_months": {
            "negative": sum(value < 0 for value in changes),
            "positive": sum(value > 0 for value in changes),
            "zero": sum(value == 0 for value in changes),
        },
        "recovery_factor": rendered(ratio(recovery)) if recovery is not None else None,
        "reference_capital_cad": "10000",
        "risk_cad": rendered(risk),
        "risk_required_to_average_monthly": {
            target: rendered(money(value)) if value is not None else None
            for target, value in inverse.items()
        },
        "total_pnl_cad": rendered(money(sum(changes))),
        "worst_month_cad": rendered(money(min(changes))),
    }


def _uniform(seed: bytes, counter: int, bound: int) -> int:
    require(bound > 0, "invalid random bound")
    limit = (1 << 256) - ((1 << 256) % bound)
    while True:
        value = int.from_bytes(hashlib.sha256(seed + counter.to_bytes(8, "big")).digest(), "big")
        counter += 1
        if value < limit:
            return value % bound


@governed_decimal
def percentile(values: list[Decimal], q: Decimal) -> Decimal:
    require(values, "empty percentile")
    ordered = sorted(values)
    h = Decimal(len(ordered) - 1) * q
    lower, upper = int(h), math.ceil(h)
    return ordered[lower] + (h - lower) * (ordered[upper] - ordered[lower])


@governed_decimal
def week_cluster_bootstrap(rows: list[dict], policy_sha256: str, replicates: int = 10_000) -> dict:
    require(replicates == 10_000, "bootstrap replicate count changed")
    clusters = defaultdict(list)
    for row in rows:
        at = timestamp(row["entry_at"]).astimezone(NY)
        iso = at.isocalendar()
        clusters[f"{iso.year:04d}-W{iso.week:02d}"].append(decimal(row["net_R"]))
    keys = sorted(clusters)
    require(keys, "bootstrap requires events")
    means = []
    for replicate in range(replicates):
        seed = hashlib.sha256(f"{policy_sha256}|{replicate:05d}".encode()).digest()
        sampled = []
        for counter in range(len(keys)):
            sampled.extend(clusters[keys[_uniform(seed, counter, len(keys))]])
        means.append(sum(sampled, Decimal(0)) / len(sampled))
    observed = _mean([decimal(row["net_R"]) for row in rows])
    return {
        "ci_95": [
            rendered(ratio(percentile(means, Decimal("0.025")))),
            rendered(ratio(percentile(means, Decimal("0.975")))),
        ],
        "cluster_count": len(keys),
        "mean_R": rendered(ratio(observed)),
        "replicates": replicates,
        "target_effect_R": "0.20",
    }


@governed_decimal
def calculate_synthetic_cohort(
    events: list[dict], expected_keys: set[str], policy_sha256: str, *, bootstrap: bool = True
) -> dict:
    """Synthetic-only cohort facade; the governed adapter supplies the fixed 82 keys."""
    keys = [row.get("physical_event_key") for row in events]
    require(len(keys) == len(set(keys)), "duplicate physical event")
    require(set(keys) == expected_keys, "missing or extra physical event")
    ordered_events = sorted(events, key=lambda row: row["physical_event_key"])
    resolutions = [resolve_event(row) for row in ordered_events]
    require(all(row["terminal"] in TERMINALS for row in resolutions), "invalid terminal")
    require(all(row["terminal"] != "UNRESOLVED_DATA" for row in resolutions), "unresolved event")
    primary = {row["physical_event_key"]: decimal(row["gross_R"]) for row in resolutions}
    chronological_r = [
        primary[event["physical_event_key"]]
        for event in sorted(
            ordered_events, key=lambda row: (row["entry_at"], row["physical_event_key"])
        )
    ]
    scenarios = {}
    scenario_summaries = {}
    for risk in RISK_LEVELS:
        event_cells = {
            event["physical_event_key"]: cost_grid(event, resolutions[index], risk)
            for index, event in enumerate(ordered_events)
        }
        scenarios[rendered(risk)] = event_cells
        by_cell = {}
        for index in range(15):
            rows = [event_cells[key][index] for key in sorted(event_cells)]
            cell_key = f"commission={rows[0]['commission_pips']}|financing={rows[0]['annual_financing_rate']}"
            by_cell[cell_key] = {
                "gross": summary_metrics([decimal(row["gross_R"]) for row in rows]),
                "net": summary_metrics([decimal(row["net_R"]) for row in rows]),
                "total_gross_cad": rendered(sum(decimal(row["gross_cad"]) for row in rows)),
                "total_net_cad": rendered(sum(decimal(row["net_cad"]) for row in rows)),
            }
        scenario_summaries[rendered(risk)] = by_cell
    base_rows = [
        {"entry_at": event["entry_at"], "net_R": rendered(primary[event["physical_event_key"]])}
        for event in ordered_events
    ]
    report = {
        "authorization": {
            "exploratory_only": True,
            "persistent_execution": False,
            "promotion": False,
        },
        "cost_scenarios": scenarios,
        "cost_scenario_summaries": scenario_summaries,
        "event_count": len(events),
        "event_results": resolutions,
        "fixed_capital": {
            rendered(risk): fixed_capital_diagnostic(ordered_events, resolutions, primary, risk)
            for risk in RISK_LEVELS
        },
        "geometry_sigma_grid": [rendered(value) for value in GEOMETRY_SIGMA_GRID],
        "hypothetical_sensitivity_sigma_grid": [
            rendered(value) for value in SENSITIVITY_SIGMA_GRID
        ],
        "metrics": summary_metrics(chronological_r),
        "statistical": week_cluster_bootstrap(base_rows, policy_sha256) if bootstrap else None,
        "terminal_counts": dict(sorted(Counter(row["terminal"] for row in resolutions).items())),
    }
    hashes = {
        "cost_scenarios_sha256": digest(report["cost_scenarios"]),
        "cost_scenario_summaries_sha256": digest(report["cost_scenario_summaries"]),
        "event_results_sha256": digest(report["event_results"]),
        "fixed_capital_sha256": digest(report["fixed_capital"]),
        "inputs_sha256": digest(ordered_events),
        "statistical_sha256": digest(report["statistical"]),
    }
    report["hashes"] = hashes
    report["report_sha256"] = digest(report)
    return report
