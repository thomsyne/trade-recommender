"""Offline effective v2 S2 policy verification; never return execution.

The loader reads fixed committed artifacts only.  It has no database, candle,
provider, outcome, return-calculator, or persistent-write path.  The accepted
v1 S2 decisions are verified through their governed loader and reused by hash;
the v2 overlay only binds the accepted v2 lineage and the owner-authorized
physical-event accounting and fixed-capital diagnostic conventions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from research import s2_geometry_v2 as geometry_v2
from research import s2_policy as policy_v1

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs/strategy/failed-break/v2"
ARTIFACT_PATH = DOCS / "s2-exploratory-policy-freeze-v2.json"
REPORT_PATH = DOCS / "s2-exploratory-policy-freeze-v2.md"

REPOSITORY_BASELINE = "c1abe04199bd7e12159c0ed933b0c5ea023e0c0c"
SCHEMA = "failed-break-v2-s2-exploratory-policy-freeze-v1"
IDENTITY = "failed-break-v2-s2-exploratory-policy-v1"
ARTIFACT_SHA256 = "1d4b1f451a60d7c2ac37a2fe91849d463254b7751529324e52198003de1ae8dc"
POLICY_SHA256 = "e2d2a4880e0d900a150a6e801d940b32b09b8cd1435f283a87fe16555e059d72"
REPORT_SHA256 = "923db60528f6c82ae635603cdb907dd956fdfdd421a2307f4283ef09b6d18165"

V1_ARTIFACT_SHA256 = "4f70ea3c86569de5b54ad3f18d7c1021b6067532ba9fb42b62faf1a0b2676e8c"
V1_POLICY_SHA256 = "c30896d2fcd943f647f93f53077e7d7d9163c455cca20aad91df8fbcd667e26f"
V1_DECISION_LEDGER_SHA256 = "7d1b0c90d2012f70141ff1987fdee8c653b4efb7bf22dfa6e8a8b046862233e5"
V1_RULES_SHA256 = "c40b3c9050776fb9d0beb72cd95144f0db6ba37b38e1c8280b59d0907f953961"
V1_METRICS_SHA256 = "537a08c7fc6a1c749b781baf0074299b479216d49a9b07c3617def1fc66481b1"
V1_MANIFEST_RULES_SHA256 = "f3ee40df7f15bdda0df8d8d7b452fc731901cb80514f80ed531c909ddbf40f65"
V1_COST_GRID_SHA256 = "b482f53f8c0da25a355f79dad7ec054561c9f642c2bf92b6f100fd73523718f7"
V1_SIGMA_GRID_SHA256 = "33f991ffdcd4e1fb2cfc7e6fda0547917d18eff0c3675f02dccb49c86948278d"
V1_CAD_ROUTES_SHA256 = "087246e0d2eb2cb630b61ebfea8f186c6534b3d558cf76c2aa059e65f28cc9ce"
V1_DECISION_HASHES = {
    "S2-01": "a63793fa48ee40ae71c6540a1d8b431e355e03367a723537199a29480c19fe3a",
    "S2-02": "f00a753b8d402601dde328b99b7f6e39bb34975ead8b339cfc2e5540b216d47e",
    "S2-03": "4bfdfe37b014a32765a30a5539d09b7c051c92b67b4f23f1985b01671b3b3d18",
    "S2-04": "def11d31ac53a0ea8774579cf99e12620e28c142d5205f3fede5e8f5b6e430fb",
    "S2-05": "227f9f443955b36138b6bb9c5307c232e4f511d867c1af25cd28d0c71342687f",
    "S2-06": "d9f44f1b742cac7d75983c8f22b7473dd5b9b570526670c5bd572b09c5ba242a",
    "S2-07": "9d10760db4e7604b23ee5b4d970acdd4ac4a8e6bb398b3a8b49a5b8c6070bfd4",
}

S1_ARTIFACT_SHA256 = "5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5"
S1_SELF_SHA256 = "5f1497b7e47da958469d8b8c13d2608243e7a0f811eb30f54f4d5fe65f2bbcab"
S1_AGGREGATE_SHA256 = "4fd959c4185034599f9eee803d476aa7249fb995d2560325071b3fc4dbb5c2d1"
GEOMETRY_ARTIFACT_SHA256 = "b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc"
GEOMETRY_SELF_SHA256 = "a3c2f7e3f3f7d722228233c158b51eaa296557daf0c19860c79848a788ffc140"
EVENT_SET_SHA256 = "8abb97a0e658d7079b9cfffd66259609b00f7c57aba89209a01cb5673df9fbd8"
MEMBERSHIPS_SHA256 = "7bf33678f10ddbb395757baf1cefd2e460ecd35cd76f28bab2d545ba504a2396"

COMBINED_BOOK = "failed-break-any-level-deduplicated-v1"
PHYSICAL_EVENTS = 82
BOOK_MEMBERSHIPS = 186


class V2PolicyRefusal(ValueError):
    """Policy identity or authority did not reconstruct exactly."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise V2PolicyRefusal(message)


def _verified_document(raw: bytes) -> dict:
    require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA256, "artifact file digest mismatch")
    try:
        document = json.loads(raw)
        require(canonical_bytes(document) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(document)
        claimed = body.pop("policy_sha256")
        require(claimed == POLICY_SHA256 == digest(body), "policy self-hash mismatch")
        return document
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise V2PolicyRefusal("invalid v2 S2 policy artifact") from error


def _expected_v1_reuse(v1: dict) -> dict:
    decisions = v1["decision_ledger"]
    actual_hashes = {row["id"]: digest(row) for row in decisions}
    require(actual_hashes == V1_DECISION_HASHES, "v1 decision bytes changed")
    expected = {
        "artifact_sha256": V1_ARTIFACT_SHA256,
        "cad_routes_sha256": V1_CAD_ROUTES_SHA256,
        "cost_grid_sha256": V1_COST_GRID_SHA256,
        "decision_hashes": V1_DECISION_HASHES,
        "decision_ledger_sha256": V1_DECISION_LEDGER_SHA256,
        "decision_status": "REUSED_EXACT_EFFECTIVE_V1_MEANING",
        "manifest_rules_sha256": V1_MANIFEST_RULES_SHA256,
        "metrics_sha256": V1_METRICS_SHA256,
        "policy_sha256": V1_POLICY_SHA256,
        "rules_sha256": V1_RULES_SHA256,
        "sigma_grid_sha256": V1_SIGMA_GRID_SHA256,
        "v1_automatic_governance_of_v2": False,
    }
    require(digest(decisions) == V1_DECISION_LEDGER_SHA256, "v1 decision ledger changed")
    require(digest(v1["rules"]) == V1_RULES_SHA256, "v1 execution rules changed")
    require(digest(v1["metrics"]) == V1_METRICS_SHA256, "v1 metric formulas changed")
    require(
        digest(v1["reconstructed_manifest_rules"]) == V1_MANIFEST_RULES_SHA256,
        "v1 manifest rules changed",
    )
    require(digest(v1["cost_grid_governance"]) == V1_COST_GRID_SHA256, "v1 cost grid changed")
    require(
        digest(v1["sigma_grid_governance"]) == V1_SIGMA_GRID_SHA256,
        "v1 sigma grid changed",
    )
    require(digest(v1["cad_routes"]) == V1_CAD_ROUTES_SHA256, "v1 CAD routes changed")
    return expected


def _expected_sources(v1: dict, geometry: dict) -> dict:
    s1 = geometry_v2.load_s1_acceptance()
    require(
        geometry["geometry_sha256"] == GEOMETRY_SELF_SHA256
        and geometry["event_set_sha256"] == EVENT_SET_SHA256
        and geometry["memberships_sha256"] == MEMBERSHIPS_SHA256
        and len(geometry["events"]) == PHYSICAL_EVENTS,
        "v2 geometry identity changed",
    )
    return {
        "accepted_v1_policy": _expected_v1_reuse(v1),
        "v2_geometry": {
            "artifact_sha256": GEOMETRY_ARTIFACT_SHA256,
            "event_set_sha256": EVENT_SET_SHA256,
            "geometry_sha256": GEOMETRY_SELF_SHA256,
            "memberships_sha256": MEMBERSHIPS_SHA256,
            "report_sha256": geometry["report_sha256"],
            "source_projection_sha256": geometry["source_projection_sha256"],
        },
        "v2_s1_acceptance": {
            "aggregate_evidence_sha256": S1_AGGREGATE_SHA256,
            "artifact_sha256": S1_ARTIFACT_SHA256,
            "configuration_sha256": s1["stored_evidence"]["hashes"]["configuration_sha256"],
            "projection_sha256": s1["stored_evidence"]["hashes"]["projection_sha256"],
            "report_sha256": s1["stored_evidence"]["hashes"]["report_sha256"],
            "self_sha256": S1_SELF_SHA256,
        },
        "v2_lineage": geometry["bindings"],
    }


def _expected_geometry_policy(geometry: dict) -> dict:
    combined = geometry["report"]["books"][COMBINED_BOOK]
    return {
        "book_memberships": BOOK_MEMBERSHIPS,
        "confirmed_setup_kish_substitution": "PROHIBITED",
        "effective_sample": {
            "conservative": "ENTRY_WEEK_KISH",
            "entry_week_kish_decimal": combined["geometry"]["entry_weeks"]["kish_decimal"],
            "entry_week_kish_exact": "1681/28",
            "shared_factor_kish_decimal": combined["geometry"]["shared_factors"]["kish_decimal"],
            "shared_factor_kish_exact": "3362/55",
        },
        "entry_dates": 76,
        "entry_weeks": 68,
        "geometry_eligible_physical_events": PHYSICAL_EVENTS,
        "membership_independence_claim": "PROHIBITED",
        "physical_events_per_month": "41/54",
        "shared_factor_clusters": 69,
        "source_entry_pending_physical_events": geometry["source_physical_events"],
        "source_entry_pending_memberships": geometry["source_entry_pending_evaluations"],
        "source_partition_boundary_purge": len(geometry["purged_events"]),
    }


def _expected_primary_unit() -> dict:
    return {
        "allocation_ordering": (
            "Retain the accepted simultaneous common-fraction ordering; first collapse every "
            "event's book memberships to one physical risk request"
        ),
        "ambiguous_or_missing_outcome": "UNRESOLVED_DATA_FAIL_CLOSED_NOT_DROPPED",
        "book_memberships_are_independent_trades": False,
        "duplicated_capital_for_multiple_books": False,
        "primary_result": "NORMALIZED_PHYSICAL_EVENT_RETURN_R",
        "risk_budget": "ONE_SHARED_PHYSICAL_EVENT_RISK_BUDGET_ACROSS_ALL_BOOK_MEMBERSHIPS",
        "terminal_classification_required": PHYSICAL_EVENTS,
        "unit": "UNIQUE_PHYSICAL_EVENT",
    }


def _expected_fixed_capital() -> dict:
    outputs = [
        "total_pnl_cad",
        "ending_reference_equity_cad",
        "average_monthly_pnl_cad",
        "median_monthly_pnl_cad",
        "positive_negative_zero_pnl_month_counts",
        "months_with_at_least_one_physical_event_entry",
        "best_month_cad",
        "worst_month_cad",
        "maximum_drawdown_cad",
        "maximum_drawdown_fraction_of_initial_capital",
        "peak_aggregate_open_risk_cad",
        "annual_pnl_cad",
        "months_at_or_above_800_cad",
        "months_at_or_above_1000_cad",
        "risk_per_trade_to_average_800_cad_monthly",
        "risk_per_trade_to_average_1000_cad_monthly",
    ]
    return {
        "accounting_currency": "CAD",
        "annual_grouping": "AMERICA_NEW_YORK_CALENDAR_YEAR_2010_THROUGH_2018",
        "capital_sufficiency_claim": False,
        "compounding": False,
        "concurrent_event_risk": "EACH_OPEN_PHYSICAL_EVENT_RETAINS_ITS_INDIVIDUAL_FIXED_RISK",
        "deposits_or_withdrawals": False,
        "diagnostic_only": True,
        "drawdown_equity_path": "V1_DAILY_17_00_NEW_YORK_SIDE_AWARE_EQUITY_MARKS",
        "ending_equity_formula": "10000_PLUS_TOTAL_FIXED_RISK_PHYSICAL_EVENT_PNL",
        "monthly_grouping": (
            "ALL_108_DEVELOPMENT_CALENDAR_MONTHS; month P&L is change between consecutive "
            "month-end governed daily-equity marks; empty unchanged months are zero"
        ),
        "monthly_target_diagnostic": {
            "formula": "target_cad_times_108_divided_by_sum_of_complete_net_physical_event_R",
            "targets_cad": ["800", "1000"],
            "undefined_when": "INCOMPLETE_TERMINAL_SET_OR_SUM_NET_R_NOT_POSITIVE",
            "use": "DIAGNOSTIC_NOT_RECOMMENDATION",
        },
        "no_leveraged_target_forcing_scenario": True,
        "outputs_each_risk_level": outputs,
        "reference_capital_cad": "10000",
        "retrospective_position_size_adjustment": False,
        "risk_grid": [
            {"cad_per_physical_event": "25", "fraction_of_reference_capital": "0.0025"},
            {"cad_per_physical_event": "50", "fraction_of_reference_capital": "0.0050"},
            {"cad_per_physical_event": "100", "fraction_of_reference_capital": "0.0100"},
        ],
        "same_event_books_share_risk": True,
        "tradability": "UNCONSTRAINED_THEORETICAL_NOTIONAL_NON_TRADABLE_WHERE_VENUE_LIMITS_FAIL",
    }


def _expected_cost_policy(v1: dict) -> dict:
    grid = v1["cost_grid_governance"]
    return {
        "additional_slippage_model": "NONE",
        "additional_slippage_pips": "0",
        "gross_R": "GOVERNED_BID_ASK_SPREAD_APPLIED_BEFORE_COMMISSION_AND_FINANCING",
        "net_R": "GROSS_R_LESS_COMMISSION_PLUS_SIGNED_FINANCING_FOR_EACH_FROZEN_CELL",
        "observed_bid_ask_spread": grid["observed_bid_ask_spread"],
        "optimistic_limitation": grid["limitation"],
        "post_result_parameter_selection": "PROHIBITED",
        "sensitivity_grid": grid["sensitivity_grid"],
    }


def _expected_statistical_policy(v1: dict, geometry: dict) -> dict:
    recommendation = v1["decision_ledger"][2]["recommendation"]
    evaluation = v1["reconstructed_manifest_rules"]["evaluation"]
    combined = geometry["report"]["books"][COMBINED_BOOK]
    return {
        "aggregation": {
            "annual": "AMERICA_NEW_YORK_CALENDAR_YEAR",
            "monthly": "AMERICA_NEW_YORK_CALENDAR_MONTH_FROM_GOVERNED_DAILY_EQUITY_MARKS",
        },
        "bootstrap": {
            "block_rounding": recommendation["block_rounding"],
            "confidence_interval": recommendation["confidence_interval"],
            "confidence_level": recommendation["confidence_level"],
            "replicate_seed": recommendation["replicate_seed"],
            "replicates": evaluation["bootstrap_replicates"],
            "resampling_unit": recommendation["week_definition"],
        },
        "cluster_treatment": (
            "Physical events remain atomic; aligned New York weeks retain all simultaneous, "
            "cross-pair and shared-factor members during resampling"
        ),
        "confirmatory_or_promotional_interpretation": "PROHIBITED",
        "geometry_mde_diagnostic": {
            "adequacy": combined["mde"]["target_0_20R_adequacy"],
            "confirmatory_adequacy_across_grid": False,
            "purpose": "RETURN_BLIND_GEOMETRY_MDE_DIAGNOSTIC",
            "sigma_R": ["0.5", "1.0", "1.5"],
        },
        "grids_interchangeable": False,
        "hypothetical_statistical_sensitivity": {
            "purpose": "HYPOTHETICAL_STATISTICAL_SENSITIVITY_SIMULATION",
            "sigma_R": ["0.5", "1.0", "2.0"],
        },
        "observed_return_grid_selection_or_reinterpretation": "PROHIBITED",
        "sharpe_sortino": recommendation["sharpe_sortino"],
        "target_effect_R": "0.20",
    }


def load_policy() -> dict:
    """Load the one fixed effective v2 policy; no caller-supplied path or override."""
    try:
        v1 = policy_v1.load_policy()
        geometry = geometry_v2.verify_committed()
        policy = _verified_document(ARTIFACT_PATH.read_bytes())
        require(
            hashlib.sha256(REPORT_PATH.read_bytes()).hexdigest() == REPORT_SHA256,
            "decision report digest mismatch",
        )
        require(
            policy["schema"] == SCHEMA
            and policy["identity"] == IDENTITY
            and policy["repository_baseline"] == REPOSITORY_BASELINE
            and policy["status"] == "EFFECTIVE_EXPLORATORY_ONLY"
            and policy["effective_at"] == "2026-09-04",
            "v2 policy identity changed",
        )
        require(
            policy["boundary"]
            == {
                "cohort": "REGISTERED_SUCCESSOR_DEVELOPMENT_2010_2018",
                "exploratory_only": True,
                "future_confirmatory_evidence": "SEPARATELY_GOVERNED_GENUINELY_UNTOUCHED_COHORT",
                "live_trading_authorization": False,
                "promotion_eligible": False,
                "promotion_permanently_prohibited": True,
                "strategy_version": "failed-break-phase-1-admission-correction-v2",
            },
            "permanent exploratory boundary changed",
        )
        require(
            policy["authorization"]
            == {
                "backtesting": False,
                "database_write": False,
                "deployment": False,
                "live_trading": False,
                "persistent_return_execution": False,
                "policy_freeze": True,
                "production_access": False,
                "promotion": False,
                "provider_access": False,
                "return_calculation": False,
                "return_calculator_implementation": False,
            },
            "authority separation changed",
        )
        require(
            policy["override_prohibition"]
            == {
                "cli": "PROHIBITED",
                "data_only": "PROHIBITED",
                "database": "PROHIBITED",
                "environment": "PROHIBITED",
                "owner": "PROHIBITED",
                "successful_future_outcome": "PROHIBITED",
                "threshold_reinterpretation_after_results": "PROHIBITED",
            },
            "override channel introduced",
        )
        require(policy["source_bindings"] == _expected_sources(v1, geometry), "source drift")
        require(
            policy["geometry_policy"] == _expected_geometry_policy(geometry),
            "geometry policy drift",
        )
        require(policy["primary_return_unit"] == _expected_primary_unit(), "return unit drift")
        require(
            policy["fixed_capital_diagnostic"] == _expected_fixed_capital(),
            "fixed-capital diagnostic drift",
        )
        require(policy["cost_policy"] == _expected_cost_policy(v1), "cost policy drift")
        require(
            policy["statistical_policy"] == _expected_statistical_policy(v1, geometry),
            "statistical policy drift",
        )
        require(
            policy["v2_specific_extensions"]
            == {
                "book_attribution": "REPORTABLE_NON_ADDITIVE_CLASSIFICATION_ONLY",
                "compatibility": "NO_UNRESOLVED_V1_POLICY_INCOMPATIBILITY",
                "physical_event_precedence": (
                    "The owner-authorized v2 physical-event unit supersedes any interpretation "
                    "that would duplicate capital across same-event books; v1 ordering remains unchanged"
                ),
                "scope": [
                    "V2_LINEAGE_AND_GEOMETRY_BINDING",
                    "ONE_PHYSICAL_EVENT_ACCOUNTING_AND_RISK_UNIT",
                    "FIXED_CAD_10000_DESCRIPTIVE_DIAGNOSTIC",
                ],
            },
            "unreviewed v2 policy extension",
        )
        require(
            policy["freeze_provenance"]
            == {
                "candle_or_post_entry_price_access": False,
                "database_access": False,
                "outcome_evidence_access": False,
                "provider_credential_or_network_access": False,
                "return_or_pnl_calculated": False,
                "sources": [
                    "COMMITTED_EFFECTIVE_V1_S2_POLICY",
                    "COMMITTED_ACCEPTED_V2_S1_OUTCOME",
                    "COMMITTED_RETURN_BLIND_V2_GEOMETRY",
                    "OWNER_AUTHORIZATION_2026-09-04",
                ],
            },
            "freeze provenance changed",
        )
        return policy
    except (KeyError, OSError, TypeError) as error:
        raise V2PolicyRefusal("incomplete committed v2 S2 policy") from error


def physical_event_risk_budgets(memberships, risk_cad):
    """Collapse book memberships to one fixed risk budget per physical event."""
    risk = Decimal(str(risk_cad))
    require(risk > 0, "physical-event risk must be positive")
    books_by_event = defaultdict(set)
    seen = set()
    for row in memberships:
        require(set(row) == {"physical_event_key", "book"}, "unexpected membership field")
        pair = (row["physical_event_key"], row["book"])
        require(all(isinstance(value, str) and value for value in pair), "invalid membership")
        require(pair not in seen, "duplicate physical-event/book membership")
        seen.add(pair)
        books_by_event[pair[0]].add(pair[1])
    return {
        event: {"books": sorted(books), "shared_risk_cad": str(risk)}
        for event, books in sorted(books_by_event.items())
    }


def readiness() -> dict:
    policy = load_policy()
    return {
        "artifact_sha256": ARTIFACT_SHA256,
        "book_memberships": policy["geometry_policy"]["book_memberships"],
        "effective_policy_integrity_verified": True,
        "exploratory_only": True,
        "geometry_eligible_physical_events": PHYSICAL_EVENTS,
        "persistent_return_execution_authorized": False,
        "policy_freeze": "AUTHORIZED_EFFECTIVE",
        "policy_sha256": POLICY_SHA256,
        "promotion_eligible": False,
        "promotion_permanently_prohibited": True,
        "return_calculator_implementation_authorized": False,
        "returns_blocked": True,
        "status": "EFFECTIVE_V2_EXPLORATORY_ONLY_RETURNS_SEPARATELY_UNAUTHORIZED",
    }


def require_frozen_policy():
    return load_policy()


def require_return_calculator_implementation(**requested_overrides):
    load_policy()
    raise V2PolicyRefusal("return-calculator implementation is separately unauthorized")


def require_persistent_return_execution(**requested_overrides):
    load_policy()
    raise V2PolicyRefusal("persistent return execution is separately unauthorized")


def require_strategy_promotion(**requested_overrides):
    load_policy()
    raise V2PolicyRefusal(
        "promotion and live trading are permanently prohibited for v2 and the 2010-2018 cohort"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-frozen", action="store_true")
    parser.add_argument("--require-return-implementation", action="store_true")
    parser.add_argument("--require-return-execution", action="store_true")
    parser.add_argument("--require-promotion", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.require_frozen:
            require_frozen_policy()
        if args.require_return_implementation:
            require_return_calculator_implementation()
        if args.require_return_execution:
            require_persistent_return_execution()
        if args.require_promotion:
            require_strategy_promotion()
        print(json.dumps(readiness(), sort_keys=True))
    except V2PolicyRefusal as error:
        parser.exit(2, f"v2 S2 refused: {error}\n")


if __name__ == "__main__":
    main()
