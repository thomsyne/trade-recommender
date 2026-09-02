"""Governed acceptance boundary for the one accepted successor S0 run."""

from __future__ import annotations

import hashlib
import json
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from django.utils.dateparse import parse_datetime

from market.services import candle_completion
from research.provider_observed import contract_for_dataset, inventory_timestamps

ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/strategy/failed-break/v1/phase-2b1r-pre-s1-s0-acceptance.json"
)
ARTIFACT_SHA256 = "225c5365219bd7653c99d8f25e113df9c5f4ad24d95b35b36f7928479bee9583"
ARTIFACT_SELF_HASH_FIELD = "acceptance_sha256"
ACCEPTED_EFFECTIVE_DATA_IDENTITY = "oanda-ba-ny17-friday-provider-observed-v2"


class S0AcceptanceError(ValueError):
    """The committed S0 acceptance or its stored evidence did not reconstruct."""


def _canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_s0_acceptance() -> dict:
    """Load only the committed artifact and verify its file and self hashes."""
    raw = ARTIFACT_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARTIFACT_SHA256:
        raise S0AcceptanceError("committed S0 acceptance file digest does not match")
    try:
        artifact = json.loads(raw)
    except json.JSONDecodeError as error:
        raise S0AcceptanceError("committed S0 acceptance is not valid JSON") from error
    if _canonical_bytes(artifact) + b"\n" != raw:
        raise S0AcceptanceError("committed S0 acceptance bytes are not canonical")
    body = dict(artifact)
    claimed = body.pop(ARTIFACT_SELF_HASH_FIELD, None)
    if claimed != hashlib.sha256(_canonical_bytes(body)).hexdigest():
        raise S0AcceptanceError("committed S0 acceptance self-hash does not match")
    if (
        artifact.get("schema") != "phase-2b1r-pre-s1-s0-acceptance-v1"
        or artifact.get("effective_data_identity") != ACCEPTED_EFFECTIVE_DATA_IDENTITY
    ):
        raise S0AcceptanceError("committed S0 acceptance identity is not governed")
    return artifact


def verify_s0_acceptance(*, job, output, dataset, strategy) -> dict:
    """Reconstruct the committed acceptance from immutable S0 and sealed inventory."""
    artifact = load_s0_acceptance()
    contract = contract_for_dataset(dataset)
    if contract is None:
        raise S0AcceptanceError("accepted S0 requires the successor data contract")
    report = output.as_dict()
    coverage = report["coverage"]
    registration = dataset.registration
    identities = {
        "configuration_sha256": job.config_hash,
        "report_sha256": output.report_sha256,
        "dataset_version": dataset.version,
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "registration_configuration_sha256": registration.configuration_sha256,
        "registration_report_sha256": registration.report_sha256,
        "data_contract_sha256": contract.sha256,
        "effective_data_identity": contract.identity,
        "global_semantic_inventory_sha256": contract.global_semantic_inventory_sha256,
        "strategy_identity": strategy.version,
        "strategy_content_hash": strategy.content_hash,
    }
    for field, actual in identities.items():
        if artifact.get(field) != actual:
            raise S0AcceptanceError(f"accepted S0 {field} does not reconstruct")

    s0 = artifact["s0"]
    if (
        s0.get("contribution_partition_counts")
        != {"development": 201101, "validation": 0, "holdout": 0, "future": 0}
        or report["counts"] != {"observations": s0["eligible_session_observations"]}
        or job.as_of.isoformat() != s0["as_of"]
        or coverage.get("row_counts") != s0["coverage_counts"]
        or coverage.get("missingness") != s0["missingness"]
        or coverage.get("spread_ceilings") != s0["spread_ceilings"]
        or coverage.get("spread_distribution_hashes") != s0["spread_distribution_hashes"]
    ):
        raise S0AcceptanceError("accepted S0 stored report does not reconstruct")

    cutoff = parse_datetime(s0["development_start"])
    development_end = parse_datetime(s0["development_end_exclusive"])
    if cutoff is None or development_end is None:
        raise S0AcceptanceError("accepted S0 development boundaries are invalid")
    warmup = {}
    latest_completion = None
    for code in sorted(s0["coverage_counts"]):
        warmup[code] = {}
        for granularity in ("D", "H1", "W"):
            timestamps = inventory_timestamps(contract, code, granularity)
            completions = tuple(
                candle_completion(timestamp, granularity, contract) for timestamp in timestamps
            )
            warmup[code][granularity] = sum(completed < cutoff for completed in completions)
            if granularity == "H1":
                eligible = [
                    candle_completion(timestamp, "H1", contract)
                    for timestamp in timestamps
                    if cutoff <= candle_completion(timestamp, "H1", contract) < development_end
                    and any(
                        time(8) <= timestamp.astimezone(ZoneInfo(zone)).time() < time(17)
                        for zone in ("Europe/London", "America/New_York")
                    )
                ]
                if eligible:
                    candidate = max(eligible)
                    latest_completion = (
                        max(latest_completion, candidate) if latest_completion else candidate
                    )
    if warmup != s0["warmup_counts"]:
        raise S0AcceptanceError("accepted S0 warm-up inventory does not reconstruct")
    if latest_completion is None or latest_completion.isoformat() != s0["latest_contribution"]:
        raise S0AcceptanceError("accepted S0 development cutoff proof does not reconstruct")
    return artifact
