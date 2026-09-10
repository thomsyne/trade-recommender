"""Non-increasing, separately attributable risk challengers and readiness."""

from datetime import datetime
from decimal import Decimal as D
from decimal import localcontext
from importlib.metadata import PackageNotFoundError, version

from market.strategy.contracts import RiskOverlay, Unavailable
from market.strategy.trend import ema

# Exact source names, not substring/LLM severity inference. Unknown names stay unknown.
EVENT_NAMES = frozenset(
    (
        "FOMC Interest Rate Decision",
        "Bank of Canada Interest Rate Decision",
        "Bank of England Interest Rate Decision",
        "ECB Interest Rate Decision",
        "CPI",
        "Consumer Price Index",
        "Employment Situation",
        "Labour Force Survey",
        "GDP",
        "Gross Domestic Product",
    )
)


def macro_overlay(inputs):
    block = inputs.payload.get("event_state", {})
    if block.get("version") != "event-state-v2":
        return RiskOverlay("macro-risk-v1", None, "event_version_unavailable")
    active = []
    for event in block.get("events", ()):
        if event.get("event_type") not in EVENT_NAMES:
            continue
        window = event.get("intraday_risk_window", {})
        if (
            window.get("state") == "available"
            and datetime.fromisoformat(window["available_at"]) <= inputs.cutoff
            and datetime.fromisoformat(window["starts_at"])
            <= inputs.cutoff
            <= datetime.fromisoformat(window["ends_at"])
        ):
            active.append(event["vintage_id"])
    if active:
        return RiskOverlay("macro-risk-v1", D(0), "named_event_pause", tuple(sorted(active)))
    spread = inputs.payload.get("granularities", {}).get("M15", {}).get("spread", {})
    # Phase4 spread is a descriptive close observation; no future fill claim.
    ratio = spread.get("spread_atr") if spread.get("state") == "available" else None
    if isinstance(ratio, str) and D(ratio) > D("0.1"):
        return RiskOverlay("macro-risk-v1", D(0), "wide_spread_pause")
    if isinstance(ratio, str) and D(ratio) > D("0.05"):
        return RiskOverlay("macro-risk-v1", D("0.5"), "spread_reduction_calendar_unknown")
    return RiskOverlay("macro-risk-v1", None, "event_coverage_unattested")


def surprise_readiness(inputs):
    # 0.12.0 cites scheduled-event vintages, but no matching consensus/release units.
    return Unavailable("macro-risk-v1", "pit_consensus_release_pair_unavailable")


def carry_readiness(inputs):
    # Policy-rate observations in macro_regime are expressly NOT forward discounts.
    return Unavailable("carry-readiness-v1", "pit_forwards_financing_rollover_ranking_unavailable")


def risk_ratio(strategy, baseline, current):
    if (
        baseline is None
        or current is None
        or not baseline.is_finite()
        or not current.is_finite()
        or baseline <= 0
        or current <= 0
    ):
        return RiskOverlay(strategy, None, "volatility_unavailable")
    with localcontext() as ctx:
        ctx.prec = 34
        return RiskOverlay(strategy, min(D(1), baseline / current), "capped_at_baseline")


def volatility_overlay(inputs, strategy):
    if strategy == "fixed-risk-v1":
        return RiskOverlay(strategy, D(1), "fixed_baseline_only")
    daily = inputs.series("D")
    if len(daily) < 98:
        return RiskOverlay(strategy, None, "daily_warmup_unavailable")
    with localcontext() as ctx:
        ctx.prec = 34
        # Percent returns improve solver scale; baseline and challengers share units.
        returns = tuple(100 * (b.close / a.close - 1) for a, b in zip(daily, daily[1:]))
        baseline = ema(tuple(r * r for r in returns[:-1]), 32).sqrt()
        if strategy == "ewma-risk-v1":
            return risk_ratio(strategy, baseline, ema(tuple(r * r for r in returns), 32).sqrt())
        if strategy != "garch-t-risk-v1":
            raise ValueError("unsupported_risk_strategy")
        return garch_overlay(returns, baseline)


def garch_overlay(returns, baseline):
    strategy = "garch-t-risk-v1"
    if not 250 <= len(returns) <= 399 or any(not r.is_finite() for r in returns):
        return RiskOverlay(strategy, None, "garch_warmup_or_nonfinite")
    try:
        for package, expected in (
            ("arch", "7.2.0"),
            ("numpy", "1.26.4"),
            ("scipy", "1.13.1"),
            ("pandas", "2.2.3"),
        ):
            if version(package) != expected:
                return RiskOverlay(strategy, None, "solver_version_unavailable")
        from arch import arch_model

        fit = arch_model(
            [float(r) for r in returns],
            mean="Zero",
            vol="GARCH",
            p=1,
            o=0,
            q=1,
            dist="StudentsT",
            rescale=False,
        ).fit(
            update_freq=0, disp="off", show_warning=False, options={"maxiter": 1000, "ftol": 1e-9}
        )
        if fit.convergence_flag != 0:
            return RiskOverlay(strategy, None, "garch_nonconvergence")
        variance = D(str(fit.forecast(horizon=1, reindex=False).variance.iloc[-1, 0]))
        if not variance.is_finite() or variance <= 0:
            return RiskOverlay(strategy, None, "garch_invalid_variance")
        return risk_ratio(strategy, baseline, variance.sqrt())
    except (ImportError, PackageNotFoundError):
        return RiskOverlay(strategy, None, "solver_dependency_unavailable")
    except (ValueError, ArithmeticError, RuntimeError):
        return RiskOverlay(strategy, None, "garch_solver_failure")
