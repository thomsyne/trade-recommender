"""Offline S2 policy reconstruction, NOT execution or policy activation.

Only the committed candidate and accepted, hash-pinned JobRun exports are read.
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
from math import ceil
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_PATH = ROOT / "docs/strategy/failed-break/v1/s2-policy-candidate-v1.json"
ARTIFACT_SHA256 = "8c4bf890213a1d1b1e965e21cf409a0ce2166cd622b608ef5e033077a51996a3"
POLICY_SHA256 = "e285d0e3aaa988f41982a8fcfc6f111fa68d13e176eb0d4c2eab636c55cf472d"
BASELINE = "7e34bdf9dbf5b43e45f638acbd685a7070d1733e"
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


def load_policy() -> dict:
    """Fixed-path, fixed-digest candidate; no environment or caller override."""
    try:
        policy = _verified_document(ARTIFACT_PATH.read_bytes(), ARTIFACT_SHA256, "policy_sha256")
        _require(policy["policy_sha256"] == POLICY_SHA256, "unreviewed policy identity")
        _require(
            policy["schema"] == "failed-break-s2-policy-candidate-v1"
            and policy["repository_baseline"] == BASELINE
            and policy["status"] == "CANDIDATE_PENDING_OWNER_AUTHORIZATION"
            and policy["effective_at"] is None
            and all(value is False for value in policy["authorization"].values()),
            "candidate cannot claim activation authority",
        )
        for relative, expected in policy["source_sha256"].items():
            path = (ROOT / relative).resolve()
            _require(path.is_relative_to(ROOT), "source outside repository")
            _require(
                hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                f"governed source changed: {relative}",
            )
        docs = ROOT / "docs/strategy/failed-break/v1"
        manifest = json.loads((docs / "phase-1-freeze-manifest.json").read_bytes())
        for field, rules in policy["reconstructed_manifest_rules"].items():
            _require(manifest[field] == rules, f"manifest rules changed: {field}")
        s0 = _verified_document(
            (docs / "phase-2b1r-pre-s1-s0-acceptance.json").read_bytes(),
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
            and all(
                d["status"] == "PENDING_OWNER_AUTHORIZATION" for d in policy["decision_ledger"]
            ),
            "decision ledger authorization mismatch",
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
    """Count-only design sensitivity; no empirical/simulated trade returns."""
    final = policy["accepted_job_evidence"][2]["evidence"]["report"]
    coverage = final["coverage"]
    eligible = coverage["simultaneous_requests"]["by_strategy_identity"][COMBINED_BOOK]["members"]
    statistical = policy["decision_ledger"][2]["recommendation"]
    effect = float(policy["decision_ledger"][4]["recommendation"]["minimum_primary_expectancy_R"])
    alpha = 1 - float(statistical["confidence_level"])
    power = float(statistical["target_design_power"])
    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)
    return {
        "basis": "HYPOTHETICAL_NORMAL_INDEPENDENT_DESIGN_NOT_OBSERVED_POWER",
        "confirmed_week_clusters_not_eligible_clusters": _cluster_facts(
            coverage["issuance_week_clusters"]
        ),
        "combined_eligible_physical_events": eligible,
        "family_plus_combined_evaluations_not_independent": final["counts"]["entry_eligible"],
        "eligible_week_factor_cluster_geometry": "NOT_IDENTIFIED_BY_ACCEPTED_AGGREGATES",
        "minimum_independent_units_at_proposed_effect_by_assumed_sigma_R": {
            str(sigma): ceil((z * sigma / effect) ** 2) for sigma in (0.5, 1, 2)
        },
        "attained_power": None,
        "sufficiency_claim": False,
    }


def readiness() -> dict:
    policy = load_policy()
    return {
        "status": "REVIEW_REQUIRED",
        "candidate_integrity_verified": True,
        "policy_sha256": policy["policy_sha256"],
        "artifact_sha256": ARTIFACT_SHA256,
        "dataset_id": DATASET_ID,
        "effective_data_identity": SUCCESSOR,
        "strategy_version_id": 1,
        "accepted_s1_report_sha256": ACCEPTED_JOBS[3][2],
        "pending_decisions": [row["id"] for row in policy["decision_ledger"]],
        "design_diagnostic": design_diagnostic(policy),
        "execution_ready": False,
        "live_database_verified": False,
        "blockers": [
            "Owner decisions and hash-bound effective-time authorization absent",
            "Eligible week/shared-factor geometry and final count-only power design not established",
            "No authorized execution/return adapter or partition-unlock authority in this gate",
        ],
    }


def require_frozen_policy():
    load_policy()
    raise PolicyRefusal(
        "S2 candidate is not an authorized effective freeze; returns remain blocked"
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
        help="Fail until a separately authorized effective policy exists",
    )
    args = parser.parse_args(argv)
    try:
        if args.require_frozen:
            require_frozen_policy()
        print(json.dumps(readiness(), sort_keys=True))
    except PolicyRefusal as error:
        parser.exit(2, f"S2 refused: {error}\n")


if __name__ == "__main__":
    main()
