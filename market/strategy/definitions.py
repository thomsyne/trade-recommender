"""Return-blind constants. Export fresh canonical objects, never mutable aliases."""

import hashlib
from pathlib import Path

from market.state.canonical import identity_digest
from market.strategy.contracts import PHASE4_DIGEST

IMPLEMENTATION_FILES = (
    "contracts.py",
    "costs.py",
    "evaluate.py",
    "orb.py",
    "risk.py",
    "setups.py",
    "simulation.py",
    "structure.py",
    "trend.py",
    "persistence.py",
    "reports.py",
)
IMPLEMENTATION_SHA256 = "554b925a6c67adc8f1cccdd7fdc086d49a0392678d63b8adaa304815a47d4591"


def verify_implementation():
    root = Path(__file__).resolve().parent
    actual = identity_digest(
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in IMPLEMENTATION_FILES
        }
    )
    if actual != IMPLEMENTATION_SHA256:
        raise ValueError("strategy_implementation_version_drift")


SPEEDS = (
    (2, 8, "10.6"),
    (4, 16, "7.5"),
    (8, 32, "5.3"),
    (16, 64, "3.75"),
    (32, 128, "2.65"),
    (64, 256, "1.875"),
)
HORIZONS = (10, 20, 40, 80, 160, 320)
STRATEGIES = (
    "ewmac-d-v1",
    "breakout-d-v1",
    "fast-mr-h1-v1",
    "pullback-m15-v1",
    "pullback-h1-v1",
    "range-m15-v1",
    "phase5-sweep-reversal-v1",
    "phase5-acceptance-continuation-v1",
    "carry-readiness-v1",
    "macro-risk-v1",
    "fixed-risk-v1",
    "ewma-risk-v1",
    "garch-t-risk-v1",
) + tuple(
    f"{variant}:{session}"
    for variant in ("orb-m15-wick-v1", "orb-m15-confirmed-v1", "orb-m15-fvg-v1")
    for session in ("london", "new_york")
)


def simulator_definition():
    return {
        "version": "adverse-next-interval-v1",
        "price": "midpoint_not_executable",
        "dual_hit": "stop_first",
        "stop_gap": "adverse_open",
        "target_gap": "no_improvement",
        "missing": "unavailable",
        "commission_sides": 2,
        "calendar": "attested_profile_known_at_decision",
        "latency": "next_interval_only",
        "financing": "cited_rollovers",
        "conversion": "cited_exit_pit",
        "costs": "complete_known_at_decision",
    }


def population_definition():
    return {
        "era": "phase5-prospective-2026-09-11-v1",
        "development": ["2026-09-11T00:00:00+00:00", "2027-01-01T00:00:00+00:00"],
        "holdout": ["2027-01-01T00:00:00+00:00", "2028-01-01T00:00:00+00:00"],
        "interval": "half_open",
        "population": "canonical12_no_eligibility_change",
        "dependence": "UTC_ISO_week_all_currencies",
        "min_untouched_weeks": 52,
        "net_mean": "strictly_positive",
        "half_holdout_net": "both_strictly_positive",
        "fvg": "positive_paired_weekly_net_increment",
        "combination": "none_between_strategies",
        "acceptance": "owner_after_independent_review",
    }


def definition(strategy):
    if strategy not in STRATEGIES:
        raise ValueError("unsupported_strategy")
    return {
        "strategy": strategy,
        "phase4_sha256": PHASE4_DIGEST,
        "specification_sha256": "d4e1f0e635f8faf800feddf5a61ec6ce88932fcdae6642930766ce31c61d3c64",
        "implementation_sha256": IMPLEMENTATION_SHA256,
        "schema": "phase5/definition-v1",
        "arithmetic": "decimal34_half_even_6dp",
        "speeds": SPEEDS,
        "horizons": HORIZONS,
        "sigma": "EMA32_squared_daily_differences_96_warmup",
        "ema": "first_seed_3span_warmup",
        "breakout": "40_centered_completed_high_low_EMA_ceil_quarter",
        "cap": "20",
        "buffer": "1",
        "diversification": "1",
        "combination": "equal_available_affordable_with_components",
        "affordability": "roundtrip_quote_cost/sigma<=0.1",
        "simulator": simulator_definition(),
        "population": population_definition(),
        "activation": "forbidden",
    }


def definition_digest(strategy):
    return identity_digest(definition(strategy))
