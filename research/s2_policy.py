"""Offline effective S2 exploratory policy verification, NOT return execution.

Only committed policy/geometry artifacts and accepted, hash-pinned JobRun exports are read.
There are no ORM, provider, strategy runner or outcome imports. Timestamp-only
helpers specify the boundary a separately authorized executor must later honor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs/strategy/failed-break/v1"
ARTIFACT_PATH = DOCS / "s2-exploratory-policy-freeze-v1.json"
ARTIFACT_SHA256 = "4f70ea3c86569de5b54ad3f18d7c1021b6067532ba9fb42b62faf1a0b2676e8c"
POLICY_SHA256 = "c30896d2fcd943f647f93f53077e7d7d9163c455cca20aad91df8fbcd667e26f"
CANDIDATE_ARTIFACT_PATH = DOCS / "s2-policy-candidate-v1.json"
CANDIDATE_ARTIFACT_SHA256 = "8c4bf890213a1d1b1e965e21cf409a0ce2166cd622b608ef5e033077a51996a3"
CANDIDATE_POLICY_SHA256 = "e285d0e3aaa988f41982a8fcfc6f111fa68d13e176eb0d4c2eab636c55cf472d"
GEOMETRY_ARTIFACT_PATH = DOCS / "s2-geometry-projection-v1.json"
GEOMETRY_ARTIFACT_SHA256 = "4749633ac8c3f28e977e7697ba9f1b9d32425de84afde183a2d0fd98e4c7b27b"
GEOMETRY_PROJECTION_SHA256 = "af2f0d6e2e865dcdc8d9825c039d5df650059e717cd09fad92b0f41ff72a8fb7"
GEOMETRY_REPORT_SHA256 = "f6f9df6a9b2c943171018a8674e659c5fd773a6ae1f4b4562ab097fd90096e8b"
SOURCE_BASELINE = "7e34bdf9dbf5b43e45f638acbd685a7070d1733e"
FREEZE_BASELINE = "58fb2bb83c58aa1397ce315ab21239da74019cd7"
CANDIDATE_COMMIT = "cfe9d19eef2f76bec2328098be77f68bf3103320"
GEOMETRY_COMMIT = "58fb2bb83c58aa1397ce315ab21239da74019cd7"
CORRECTION_PARENT_COMMIT = "aa8224fb1125258556a816c0e961db1b0f0a094a"
S2_03_SIGMA_GRID = ("0.5", "1.0", "2.0")
GEOMETRY_MDE_SIGMA_GRID = ("0.5", "1.0", "1.5")
ACCEPTED_JOBS = {
    1: (
        "failed-break-signal-count-s0",
        "a76fdcc90f85f6b1f1216a672e1bc01c3409d760c2e2a5d2cbc12d44498968b2",
        "85f5fa661a25756aa14cdd98be1bee11932068dcdda55165fcd4abf063cebff3",
    ),
    2: (
        "failed-break-signal-count-s1-detector",
        "f5f903ea2fc6334551156a468cb8cf1b0b4a9f1d15922ecf2a331750a89a0fe4",
        "d7eb69678594665d7d47355f5e973a10bfe9a19a9f6e5359a301df7040811ecb",
    ),
    3: (
        "failed-break-signal-count-s1",
        "24337317fec53b65a8537d534fb6646840cf9e564b04ee81e4ea6ba3cfb6b770",
        "cf9a7e9d1964c7c1952698b1c9bf9343e40265fba9fbda68aa63eeb3a4400418",
    ),
}
COMBINED_BOOK = "failed-break-any-level-deduplicated-v1"
SUCCESSOR = "oanda-ba-ny17-friday-provider-observed-v2"
DATASET_ID = 3


class PolicyRefusal(ValueError):
    """Unverifiable evidence or authority; no inference or fallback is permitted."""


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise PolicyRefusal(message)


def _verified_document(raw, file_hash, self_field):
    _require(hashlib.sha256(raw).hexdigest() == file_hash, "artifact file digest mismatch")
    try:
        document = json.loads(raw)
        _require(canonical_bytes(document) + b"\n" == raw, "artifact bytes not canonical")
        body = dict(document)
        claimed = body.pop(self_field)
        _require(digest(body) == claimed, "artifact self-hash mismatch")
        return document
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise PolicyRefusal("invalid structured artifact") from error


def _verify_jobs(jobs):
    """Pure reconstruction of pinned stored reports, not an arbitrary input API."""
    _require([job["id"] for job in jobs] == [1, 2, 3], "accepted JobRun set changed")
    for job in jobs:
        _require(
            set(job)
            == {
                "id",
                "job_name",
                "config_hash",
                "status",
                "evidence",
                "dataset_version_id",
                "strategy_version_id",
            },
            "unexpected JobRun fields",
        )
        name, config_hash, report_hash = ACCEPTED_JOBS[job["id"]]
        _require(
            job["job_name"] == name
            and job["status"] == "succeeded"
            and job["dataset_version_id"] == DATASET_ID
            and job["strategy_version_id"] == 1
            and job["config_hash"] == config_hash,
            "accepted JobRun lineage/status changed",
        )
        _require(set(job["evidence"]) == {"configuration", "report"}, "unexpected evidence")
        config, report = job["evidence"]["configuration"], job["evidence"]["report"]
        _require(digest(config) == config_hash, "accepted configuration hash mismatch")
        body = {key: value for key, value in report.items() if key != "report_sha256"}
        _require(
            report["report_sha256"] == report_hash == digest(body),
            "accepted report hash mismatch (changed/forbidden evidence)",
        )
        _require(config["dataset_id"] == DATASET_ID, "predecessor routing refused")
        if job["id"] != 2:
            _require(config["effective_data_identity"] == SUCCESSOR, "wrong effective contract")
            _require(report["configuration_sha256"] == config_hash, "report/config link mismatch")

    detector = jobs[1]["evidence"]["report"]
    final = jobs[2]["evidence"]["report"]
    _require(
        detector["complete"] is True
        and detector["expected_analysis_count"] == detector["observed_analysis_count"] == 344667
        and detector["expected_analysis_sha256"] == detector["observed_analysis_sha256"]
        and detector["data_incomplete_count"] == detector["data_quality_cancellation_count"] == 0,
        "detector coverage incomplete",
    )
    _require(
        final["coverage"]["complete"] is True
        and final["counts"]["physical_setups_processed"] == 316
        and final["counts"]["entry_eligible"] == 204
        and final["counts"]["partition_boundary_purged"] == 1
        and all(value == 0 for value in final["coverage"]["data_quality_coverage"].values()),
        "accepted S1 coverage/data-quality mismatch",
    )
    return final


def load_candidate_policy() -> dict:
    """Historical reviewed candidate, retained as the exact defaults source."""
    try:
        policy = _verified_document(
            CANDIDATE_ARTIFACT_PATH.read_bytes(),
            CANDIDATE_ARTIFACT_SHA256,
            "policy_sha256",
        )
        _require(
            policy["schema"] == "failed-break-s2-policy-candidate-v1"
            and policy["repository_baseline"] == SOURCE_BASELINE
            and policy["policy_sha256"] == CANDIDATE_POLICY_SHA256
            and policy["status"] == "CANDIDATE_PENDING_OWNER_AUTHORIZATION"
            and policy["effective_at"] is None
            and all(value is False for value in policy["authorization"].values()),
            "historical candidate identity/authority changed",
        )
        return policy
    except (KeyError, TypeError, OSError) as error:
        raise PolicyRefusal("incomplete committed S2 candidate") from error


def _load_geometry() -> dict:
    geometry = _verified_document(
        GEOMETRY_ARTIFACT_PATH.read_bytes(),
        GEOMETRY_ARTIFACT_SHA256,
        "projection_sha256",
    )
    _require(
        geometry["projection_sha256"] == GEOMETRY_PROJECTION_SHA256
        and geometry["report_sha256"] == GEOMETRY_REPORT_SHA256
        and digest(geometry["report"]) == GEOMETRY_REPORT_SHA256
        and digest(geometry["events"]) == geometry["event_set_sha256"]
        and geometry["candidate_commit"] == CANDIDATE_COMMIT
        and geometry["candidate_policy_sha256"] == CANDIDATE_POLICY_SHA256
        and geometry["authorization_effective"] is False,
        "return-blind geometry identity changed",
    )
    return geometry


def _expected_geometry_acceptance(geometry):
    combined = geometry["report"]["books"][COMBINED_BOOK]
    return {
        "cohort": "REGISTERED_SUCCESSOR_2010_2018",
        "confirmatory_adequacy_across_geometry_mde_diagnostic_grid": False,
        "confirmed_setup_kish": "PROHIBITED_SUBSTITUTE_FOR_TRADE_LEVEL_EFFECTIVE_SAMPLE_SIZE",
        "mde_adequacy_at_minimum_primary_expectancy_R_0_20": {
            "sigma_0_5_R": "ADEQUATE",
            "sigma_1_0_R": "NOT_ADEQUATE",
            "sigma_1_5_R": "NOT_ADEQUATE",
        },
        "mde_R_entry_week_kish": combined["mde_R_eligible_geometry"]["entry_week_kish"],
        "mde_R_shared_factor_kish": combined["mde_R_eligible_geometry"]["shared_factor_kish"],
        "physical_events": combined["eligible_physical_count"],
        "singleton_408_statistic": "NON_AUTHORITATIVE_NOT_INDEPENDENCE_EVIDENCE",
        "trade_level_entry_week_kish": combined["geometry"]["entry_weeks"]["kish_exact"],
        "trade_level_shared_factor_kish": combined["geometry"]["shared_factors"]["kish_exact"],
    }


def _expected_sigma_grid_governance(candidate, geometry):
    design_sensitivity = candidate["decision_ledger"][2]["recommendation"]["design_sensitivity"]
    _require(
        design_sensitivity
        == (
            "Analytical normal-design sensitivity only: hypothetical sigma_R in [0.5,1,2], "
            "not estimated from returns. Eligible event/week cluster geometry is not present in "
            "the accepted aggregate; do not treat confirmed-week Kish as eligible independence "
            "or claim achieved power."
        ),
        "S2-03 statistical-sensitivity source changed",
    )
    geometry_grid = geometry["report"]["sigma_grid_governance"]
    _require(
        geometry_grid
        == {
            "interchangeable_with_s2_03": False,
            "observed_return_selection_or_reinterpretation": "PROHIBITED",
            "overrides_s2_03": False,
            "promotion_authority": False,
            "purpose": "RETURN_BLIND_GEOMETRY_MDE_DIAGNOSTIC",
            "sigma_R": list(GEOMETRY_MDE_SIGMA_GRID),
        }
        and geometry["report"]["sigma_R"] == list(GEOMETRY_MDE_SIGMA_GRID),
        "geometry/MDE diagnostic grid changed",
    )
    return {
        "geometry_mde_diagnostic": {
            **geometry_grid,
            "adequacy_at_practical_effect_target_R_0_20": {
                "sigma_0_5_R": "ADEQUATE",
                "sigma_1_0_R": "NOT_ADEQUATE",
                "sigma_1_5_R": "NOT_ADEQUATE",
            },
            "confirmatory_adequacy_across_grid": False,
        },
        "relationship": {
            "interchangeable": False,
            "observed_return_may_select_replace_or_reinterpret": False,
            "override": "NEITHER_GRID_OVERRIDES_THE_OTHER",
        },
        "s2_03_statistical_sensitivity": {
            "hypothetical": True,
            "observed_return_selection_or_estimation": "PROHIBITED",
            "purpose": "HYPOTHETICAL_STATISTICAL_SENSITIVITY_SIMULATION",
            "sigma_R": list(S2_03_SIGMA_GRID),
        },
    }


def _expected_cost_grid_governance(candidate):
    recommendation = candidate["decision_ledger"][1]["recommendation"]
    sensitivity = candidate["reconstructed_manifest_rules"]["costs"]["sensitivity"]
    _require(
        recommendation["additional_slippage_pips"] == "0"
        and recommendation["semantics"]
        == (
            "No additional slippage model, not a claim that historical slippage was zero; retain "
            "adverse gap and stop-first rules. Commission unknown/excluded and financing "
            "unavailable/excluded in primary."
        )
        and sensitivity["identity"] == "cost-commission-financing-grid-v1"
        and sensitivity["round_turn_commission_pips"] == [0, 0.5, 1]
        and sensitivity["annual_notional_financing_rates"] == [-0.06, -0.03, 0, 0.03, 0.06],
        "S2-02 cost source changed",
    )
    return {
        "additional_slippage_model": "NONE",
        "additional_slippage_pips": "0",
        "limitation": {
            "additional_execution_slippage_beyond_governed_bid_ask_spread": "EXCLUDED",
            "assessment": "OPTIMISTIC_LIMITATION",
            "exploratory_results_cannot_authorize_promotion_or_live_trading": True,
            "future_slippage_model_requires": [
                "NEW_STRATEGY_POLICY_VERSION",
                "GENUINELY_UNTOUCHED_CONFIRMATORY_EVIDENCE",
            ],
        },
        "observed_bid_ask_spread": "APPLIED_UNDER_GOVERNED_EXECUTION_CONVENTION",
        "sensitivity_grid": {
            "axes": [
                "round_turn_commission_pips",
                "annual_notional_financing_rates",
            ],
            "annual_notional_financing_rates": sensitivity["annual_notional_financing_rates"],
            "cell_count": 15,
            "classification": "COMMISSION_X_FINANCING_NOT_SLIPPAGE",
            "identity": sensitivity["identity"],
            "round_turn_commission_pips": sensitivity["round_turn_commission_pips"],
            "slippage_axis": False,
        },
    }


def load_policy() -> dict:
    """Fixed-path, exact effective freeze; no caller/environment/DB override."""
    try:
        candidate = load_candidate_policy()
        geometry = _load_geometry()
        policy = _verified_document(ARTIFACT_PATH.read_bytes(), ARTIFACT_SHA256, "policy_sha256")
        _require(policy["policy_sha256"] == POLICY_SHA256, "unreviewed effective policy")
        _require(
            policy["schema"] == "failed-break-s2-exploratory-policy-freeze-v1"
            and policy["repository_baseline"] == FREEZE_BASELINE
            and policy["status"] == "EFFECTIVE_EXPLORATORY_ONLY"
            and policy["effective_at"] == "2026-09-03"
            and policy["exploratory_only"] is True
            and policy["promotion_eligible"] is False
            and policy["promotion_permanently_prohibited"] is True,
            "effective exploratory boundary changed",
        )
        _require(
            policy["clarification_source"]
            == {
                "authorized_scope": "SIGMA_GRID_AND_COST_GRID_DESCRIPTIONS_ONLY",
                "parent_commit": CORRECTION_PARENT_COMMIT,
            }
            and policy["sigma_grid_governance"]
            == _expected_sigma_grid_governance(candidate, geometry)
            and policy["cost_grid_governance"] == _expected_cost_grid_governance(candidate),
            "authorized sigma/cost clarification changed",
        )
        _require(
            policy["authorization"]
            == {
                "automatic_promotion": False,
                "exploratory_return_execution": False,
                "partition_unlock": False,
                "persistent_write": False,
                "policy_execution": False,
                "policy_freeze": True,
                "provider_access": False,
                "return_calculation": False,
                "strategy_promotion": False,
            }
            and policy["authority_separation"]
            == {
                "exploratory_return_execution": "SEPARATELY_UNAUTHORIZED",
                "policy_freeze": "AUTHORIZED_EFFECTIVE",
                "strategy_promotion": "PERMANENTLY_PROHIBITED",
            },
            "authorization separation changed or override introduced",
        )
        _require(
            policy["exploratory_boundary"]
            == {
                "applies_to_cohort": "REGISTERED_SUCCESSOR_2010_2018",
                "future_confirmatory_requirement": (
                    "SEPARATELY_GOVERNED_GENUINELY_UNTOUCHED_COHORT"
                ),
                "live_trading_authorization_path": "NONE_PERMANENTLY_PROHIBITED",
                "outcome_independent": (
                    "PERMANENT_NON_PROMOTION_REGARDLESS_OF_ANY_OBSERVED_OUTCOME"
                ),
                "practical_effect_target_after_geometry": "IMMUTABLE_0.20R",
                "promotion_override_channels": {
                    "cli": "PROHIBITED",
                    "data_only": "PROHIBITED",
                    "database": "PROHIBITED",
                    "environment": "PROHIBITED",
                    "owner": "PROHIBITED",
                },
                "promotion_path": "NONE",
            },
            "permanent cohort prohibition changed",
        )
        _require(
            policy["promotion_language_supersession"]
            == {
                "effective_rule": "NO_OWNER_OR_OTHER_PROMOTION_PATH",
                "retained_candidate_language": (
                    "VERBATIM_FOR_REVIEW_TRACEABILITY_NOT_EFFECTIVE_PROMOTION_AUTHORITY"
                ),
                "scope": (
                    "All promotion, not-promotable and owner-gate wording inside the verbatim "
                    "S2-01 through S2-07 recommendation payloads is subordinate to the permanent "
                    "exploratory boundary."
                ),
                "superseded_path": "decision_ledger[S2-05].recommendation.owner_gate",
            },
            "historical owner-gate wording was not subordinated",
        )
        _require(
            policy["candidate_source"]
            == {
                "artifact_sha256": CANDIDATE_ARTIFACT_SHA256,
                "candidate_commit": CANDIDATE_COMMIT,
                "policy_sha256": CANDIDATE_POLICY_SHA256,
                "schema": "failed-break-s2-policy-candidate-v1",
            }
            and policy["geometry_source"]
            == {
                "artifact_sha256": GEOMETRY_ARTIFACT_SHA256,
                "artifact_revision": "ADDITIVE_POLICY_CLARIFICATION",
                "event_set_sha256": geometry["event_set_sha256"],
                "projection_sha256": GEOMETRY_PROJECTION_SHA256,
                "report_sha256": GEOMETRY_REPORT_SHA256,
                "source_geometry_commit": GEOMETRY_COMMIT,
                "source_projection_sha256": geometry["source_projection_sha256"],
            }
            and policy["geometry_acceptance"] == _expected_geometry_acceptance(geometry),
            "candidate/geometry binding or adequacy statement changed",
        )
        for relative, expected in policy["source_sha256"].items():
            path = (ROOT / relative).resolve()
            _require(path.is_relative_to(ROOT), "source outside repository")
            _require(
                hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                f"governed source changed: {relative}",
            )
        manifest = json.loads((DOCS / "phase-1-freeze-manifest.json").read_bytes())
        for field, rules in policy["reconstructed_manifest_rules"].items():
            _require(manifest[field] == rules, f"manifest rules changed: {field}")
        s0 = _verified_document(
            (DOCS / "phase-2b1r-pre-s1-s0-acceptance.json").read_bytes(),
            policy["pre_s1_governance"]["s0_acceptance_artifact_sha256"],
            "acceptance_sha256",
        )
        final = _verify_jobs(policy["accepted_job_evidence"])
        _require(
            policy["pre_s1_governance"] == final["coverage"]["pre_s1_governance"]
            and digest(policy["pre_s1_governance"]) == final["coverage"]["pre_s1_governance_sha256"]
            and digest(policy["cad_routes"])
            == policy["pre_s1_governance"]["cad_conversion_route_sha256"],
            "pre-S1 governance/CAD routes do not reconstruct",
        )
        _require(
            policy["rules"]["costs"]["spread_ceilings"] == s0["s0"]["spread_ceilings"]
            and policy["rules"]["costs"]["spread_distribution_hashes"]
            == s0["s0"]["spread_distribution_hashes"]
            and final["coverage"]["s0_report_sha256"] == s0["report_sha256"],
            "accepted S0 cost freeze changed",
        )
        for field in ("registration_configuration_sha256", "registration_report_sha256"):
            _require(policy["lineage"][field] == s0[field], "registration identity mismatch")
        _require(
            [d["id"] for d in policy["decision_ledger"]] == [f"S2-{i:02d}" for i in range(1, 8)]
            and all(d["status"] == "RESOLVED_OWNER_AUTHORIZED" for d in policy["decision_ledger"])
            and [
                {key: value for key, value in row.items() if key != "status"}
                for row in policy["decision_ledger"]
            ]
            == [
                {key: value for key, value in row.items() if key != "status"}
                for row in candidate["decision_ledger"]
            ],
            "seven decisions not resolved from exact reviewed defaults",
        )
        _require(
            policy["metrics"]["status"]
            == "FORMULAS_FROZEN_EXPLORATORY_RETURN_EXECUTION_SEPARATELY_UNAUTHORIZED"
            and policy["future_execution_contract"]["authority"] is False
            and policy["future_execution_contract"]["implemented"] is False
            and all(
                policy["freeze_provenance"][field] is False
                for field in (
                    "candle_payload_read",
                    "database_read",
                    "outcome_evidence_accessed",
                    "provider_or_network_access",
                    "return_calculated",
                )
            ),
            "return execution or outcome access claimed by freeze",
        )
        return policy
    except (KeyError, TypeError, OSError) as error:
        raise PolicyRefusal("incomplete committed S2 evidence") from error


def _cluster_facts(summary):
    sizes = {int(size): count for size, count in summary["size_distribution"].items()}
    _require(
        all(size > 0 and type(count) is int and count > 0 for size, count in sizes.items()),
        "invalid cluster histogram",
    )
    members = sum(size * count for size, count in sizes.items())
    _require(
        sum(sizes.values()) == summary["clusters"] and members == summary["members"],
        "cluster histogram does not reconstruct",
    )
    squared = sum(size * size * count for size, count in sizes.items())
    return {
        "members": members,
        "raw_clusters": sum(sizes.values()),
        "kish_exact": str(Fraction(members * members, squared)) if squared else None,
    }


def design_diagnostic(policy) -> dict:
    """Accepted actual return-blind geometry; never a return or power estimate."""
    geometry = policy["geometry_acceptance"]
    return {
        "basis": "ACCEPTED_RETURN_BLIND_TRADE_LEVEL_GEOMETRY",
        "combined_eligible_physical_events": geometry["physical_events"],
        "entry_week_kish_exact": geometry["trade_level_entry_week_kish"],
        "shared_factor_kish_exact": geometry["trade_level_shared_factor_kish"],
        "minimum_detectable_effect_R": {
            "entry_week_kish": geometry["mde_R_entry_week_kish"],
            "shared_factor_kish": geometry["mde_R_shared_factor_kish"],
        },
        "adequacy_at_0_20R": geometry["mde_adequacy_at_minimum_primary_expectancy_R_0_20"],
        "confirmatory_adequacy_across_geometry_mde_diagnostic_grid": False,
        "sigma_grid_governance": policy["sigma_grid_governance"],
        "singleton_408_statistic": geometry["singleton_408_statistic"],
        "confirmed_setup_kish": geometry["confirmed_setup_kish"],
        "attained_power": None,
    }


def readiness() -> dict:
    policy = load_policy()
    return {
        "status": "EFFECTIVE_EXPLORATORY_ONLY_RETURNS_SEPARATELY_UNAUTHORIZED",
        "effective_policy_integrity_verified": True,
        "policy_sha256": policy["policy_sha256"],
        "artifact_sha256": ARTIFACT_SHA256,
        "dataset_id": DATASET_ID,
        "effective_data_identity": SUCCESSOR,
        "strategy_version_id": 1,
        "accepted_s1_report_sha256": ACCEPTED_JOBS[3][2],
        "resolved_decisions": [row["id"] for row in policy["decision_ledger"]],
        "design_diagnostic": design_diagnostic(policy),
        "cost_grid_governance": policy["cost_grid_governance"],
        "sigma_grid_governance": policy["sigma_grid_governance"],
        "exploratory_only": True,
        "promotion_eligible": False,
        "promotion_permanently_prohibited": True,
        "policy_freeze_authorized": True,
        "exploratory_return_execution_authorized": False,
        "strategy_promotion_authorized": False,
        "returns_blocked": True,
        "execution_ready": False,
        "live_database_verified": False,
        "blockers": [
            "Exploratory return execution remains separately unauthorized",
            "No authorized execution/return adapter or persistent-write authority exists in this gate",
        ],
    }


def require_frozen_policy():
    """Verify and return the effective policy; grants no execution authority."""
    return load_policy()


def require_exploratory_return_execution(**requested_overrides):
    """A separate authorization and implementation are required after this freeze."""
    load_policy()
    raise PolicyRefusal(
        "exploratory return execution is separately unauthorized; policy freeze is not execution"
    )


def require_strategy_promotion(**requested_overrides):
    """Irreversible policy/cohort prohibition; overrides are deliberately powerless."""
    load_policy()
    raise PolicyRefusal(
        "strategy promotion is permanently prohibited for this policy and 2010-2018 cohort"
    )


@dataclass(frozen=True, slots=True)
class SealedMember:
    """Inventory metadata only: no candle price or outcome can inhabit this type."""

    instrument: str
    granularity: str
    opened_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class AdmittedReference:
    member: SealedMember
    evidence_sha256: str
    dataset_id: int = DATASET_ID
    complete: bool = True
    successful: bool = True
    conflicting: bool = False


def _aware(timestamp):
    _require(
        isinstance(timestamp, datetime) and timestamp.utcoffset() is not None,
        "timezone-aware decision metadata required",
    )


class SealedMetadataIndex:
    """Preloaded inventory adjacency, O(log N) selection; no ORM or payload reader.

    Expected membership and admitted evidence remain separate. An absent required
    row is a failure, never a reason to fall back to an older conversion candle.
    Future horizon operations return timestamps only, not future price evidence.
    """

    def __init__(self, inventory: Iterable[SealedMember], references: Iterable[AdmittedReference]):
        self._series = {}
        self._references = {}
        self._members = set()
        self._queries = 0
        keys = set()
        for member in inventory:
            _aware(member.opened_at)
            _aware(member.completed_at)
            _require(member.completed_at > member.opened_at, "invalid interval")
            _require(member.granularity in {"H1", "D"}, "unsupported sealed granularity")
            key = (member.instrument, member.granularity, member.opened_at)
            _require(key not in keys, "duplicate/conflicting sealed inventory")
            keys.add(key)
            self._members.add(member)
            self._series.setdefault(key[:2], []).append(member)
        self._opens, self._completions = {}, {}
        for key, members in self._series.items():
            members.sort(key=lambda member: member.opened_at)
            _require(
                all(a.completed_at <= b.opened_at for a, b in zip(members, members[1:])),
                "overlapping sealed intervals",
            )
            self._opens[key] = tuple(row.opened_at for row in members)
            self._completions[key] = tuple(row.completed_at for row in members)
        for reference in references:
            _require(reference.member in self._members, "unregistered evidence")
            _require(reference.member not in self._references, "duplicate/conflicting evidence")
            self._references[reference.member] = reference

    def _admitted(self, member, as_of):
        _aware(as_of)
        row = self._references.get(member)
        _require(row is not None, "DATA_INCOMPLETE: expected sealed evidence missing")
        _require(
            row.dataset_id == DATASET_ID
            and row.complete is True
            and row.successful is True
            and row.conflicting is False
            and member.completed_at <= as_of
            and len(row.evidence_sha256) == 64
            and all(c in "0123456789abcdef" for c in row.evidence_sha256),
            "DATA_INCOMPLETE: unavailable/conflicting evidence or wrong dataset",
        )
        return row

    def latest_conversion_before(self, instrument, decision_at):
        _aware(decision_at)
        self._queries += 1
        key = (instrument, "H1")
        index = bisect_left(self._completions.get(key, ()), decision_at) - 1
        _require(index >= 0, "DATA_INCOMPLETE: no strictly prior conversion member")
        return self._admitted(self._series[key][index], decision_at)

    def next_entry(self, instrument, confirmation_at, admitted_as_of):
        _aware(confirmation_at)
        self._queries += 1
        key = (instrument, "H1")
        index = bisect_left(self._opens.get(key, ()), confirmation_at)
        members = self._series.get(key, ())
        _require(index < len(members), "DATA_INCOMPLETE: no sealed entry successor")
        return self._admitted(members[index], admitted_as_of)

    def maximum_horizon_timestamp(self, instrument, entry_at):
        _aware(entry_at)
        self._queries += 1
        daily = self._completions.get((instrument, "D"), ())
        index = bisect_right(daily, entry_at) + 9
        _require(index < len(daily), "DATA_INCOMPLETE: fewer than ten provider D sessions")
        hourly = self._opens.get((instrument, "H1"), ())
        next_index = bisect_left(hourly, daily[index])
        _require(next_index < len(hourly), "DATA_INCOMPLETE: no sealed horizon exit open")
        return hourly[next_index]

    @property
    def progress(self):
        return {
            "expected_sealed_members": len(self._members),
            "loaded_members": len(self._references),
            "metadata_queries": self._queries,
        }


def require_projection(*, purpose, fields, member, decision_at, admitted_as_of):
    """Field authorization only; does not read, resolve or return any candle value."""
    _aware(decision_at)
    _aware(admitted_as_of)
    _aware(member.opened_at)
    _aware(member.completed_at)
    allowed = {
        "entry_open": frozenset({"timestamp", "bid_open", "ask_open"}),
        "conversion": frozenset({"timestamp", "completed_at", "midpoint_close"}),
    }
    _require(
        purpose in allowed and frozenset(fields) == allowed[purpose],
        "forbidden projection; no outcome/high/low/close/volume reader",
    )
    _require(
        member.granularity == "H1" and member.completed_at <= admitted_as_of,
        "unavailable H1 evidence",
    )
    if purpose == "entry_open":
        _require(member.opened_at == decision_at, "entry projection shifted from decision")
    else:
        _require(
            member.completed_at < decision_at, "conversion must complete strictly before decision"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-frozen",
        action="store_true",
        help="Verify the fixed effective policy without granting return execution",
    )
    parser.add_argument(
        "--require-return-execution",
        action="store_true",
        help="Fail closed: return execution remains separately unauthorized",
    )
    parser.add_argument(
        "--require-promotion",
        action="store_true",
        help="Fail closed: this policy/cohort is permanently non-promotable",
    )
    args = parser.parse_args(argv)
    try:
        if args.require_frozen:
            require_frozen_policy()
        if args.require_return_execution:
            require_exploratory_return_execution()
        if args.require_promotion:
            require_strategy_promotion()
        print(json.dumps(readiness(), sort_keys=True))
    except PolicyRefusal as error:
        parser.exit(2, f"S2 refused: {error}\n")


if __name__ == "__main__":
    main()
