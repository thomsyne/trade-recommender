"""Gate 8B: governance for the successor provider-observed discovery plan.

The registered v2 dataset satisfies every lineage, coverage and registration
check but is refused at the S0 boundary: each H1 series carries eight eligible
completed warm-up candles where ATR14 requires fourteen. The six missing hours
are the New Year closure, and the sealed inventory proves the provider observed
nothing there, so they cannot be acquired. Warm-up depth must instead come from
candles earlier than the v2 H1 request start.

This module freezes that governed boundary, builds the successor discovery plan
deterministically offline, derives its staged execution membership, and loads
the committed authorization artifact by byte comparison. It performs no
database write, constructs no provider client and issues no network request.

Two rules govern warm-up and are recorded here rather than implemented as a
calendar filter:

* Depth is counted in completed provider-observed H1 candles. A weekend,
  public holiday or provider closure contributes nothing unless the sealed
  inventory holds an actual observation.
* An observed timestamp is never discarded because a theoretical calendar
  labels it a weekend or holiday.

Gate 8B records both rules and observes nothing. Enforcement against real
membership belongs to the separately authorized gates that follow.
"""

import hashlib
import json
from pathlib import Path

from market.historical_acquisition import INSTRUMENTS
from market.historical_discovery import (
    DISCOVERY_COMPLETION_SUMMARY_SHA256,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_IDENTITY,
    DISCOVERY_V2_PLAN_SHA256,
    DISCOVERY_V2_VERSION,
    GLOBAL_SEMANTIC_INVENTORY_SHA256,
    build_provider_observed_discovery_plan,
    canonical_hash,
    parse_timestamp,
)

ARTIFACT_SCHEMA = "phase-2b1r-gate8b-successor-discovery-authorization-v1"
ARTIFACT_NAME = "phase-2b1r-gate8b-successor-discovery-authorization.json"

SUCCESSOR_DISCOVERY_VERSION = "phase-2b1r-discovery-v3"
SUCCESSOR_DISCOVERY_PLAN_IDENTITY = "failed-break-phase-2b1r-discovery-plan-v3"

# The governed structural boundary. This literal is the authority: it is never
# computed from DEVELOPMENT_START, never reconstructed from the theoretical
# calendar, never selected from observed timestamps, and never moved once
# discovery has run. The calendar cannot derive it, because the calendar is
# what misclassified the six New Year closure hours as open.
SUCCESSOR_H1_REQUESTED_FROM = "2009-12-30T22:00:00Z"

# The design digest this implementation was authorized against.
DESIGN_REPORT_DIGEST = "44cec90e08a25e742c960b934f9f9e062a5ebcfcd8305c545f8ebd48d7a16211"
AUTHORIZED_BASELINE_COMMIT = "6240b31e1d3411c79db0f4c40e0fe29fde11f2d5"

# Accepted predecessor identities, bound as evidence rather than recomputed.
PREDECESSOR_REGISTRATION_CONFIGURATION_SHA256 = (
    "ba62a1f05c87abd44be1f49c0b142ee60d83c61c514adaa9b6b73221cf1840f5"
)
PREDECESSOR_REGISTRATION_REPORT_SHA256 = (
    "eeb3992b955bd503114a47a68c3c39a6b1c7136b05d1966a59029121859221bd"
)

EXPECTED_CHUNK_COUNT = 132
EXPECTED_GRANULARITY_CHUNKS = {"D": 6, "H1": 120, "W": 6}
EXPECTED_INSTRUMENT_CHUNKS = {"D": 1, "H1": 20, "W": 1}

# The staged execution structure, derived from the plan rather than duplicated.
CANARY_INSTRUMENT = "AUD_USD"
STAGE_CANARY = "gate8c_canary"
STAGE_CROSS_INSTRUMENT = "gate8d1_cross_instrument"
STAGE_REMAINDER = "gate8d2_remainder"
EXPECTED_STAGE_COUNTS = {STAGE_CANARY: 1, STAGE_CROSS_INSTRUMENT: 5, STAGE_REMAINDER: 126}

# Attempt policy: the authorized plan is one attempt per chunk. A failure stops
# its gate; nothing retries automatically. Any retry needs its own
# authorization and its own separately reviewed governance migration.
MAX_ATTEMPTS_PER_CHUNK = 1
EXPECTED_ATTEMPT_COUNT = EXPECTED_CHUNK_COUNT

# Every instrument must reach this many eligible completed provider-observed H1
# candles, counted from sealed observations only. Gate 8B records the
# requirement; it observes nothing.
REQUIRED_H1_WARMUP_OBSERVATIONS = 14

WARMUP_ACCEPTANCE_RULE = (
    "Warm-up depth counts completed provider-observed H1 candles whose completion falls at"
    " or before the unchanged development start. A weekend, public holiday or provider"
    " closure contributes zero candles unless the sealed inventory holds an actual"
    " observation, and an observed timestamp is never discarded because a theoretical"
    " calendar labels it a weekend or holiday. No exclusion list exists or may be added."
)

AUTHORIZATION_SCOPE = (
    "authorizes successor discovery-plan code and future migration design only;"
    " it does not authorize applying any migration, materializing a plan, contacting the"
    " provider, running discovery or acquisition, registering a dataset, S0, S1 or returns"
)


def successor_h1_requested_from():
    """The governed boundary as an aware datetime, parsed from its literal."""
    return parse_timestamp(SUCCESSOR_H1_REQUESTED_FROM)


def build_successor_discovery_plan():
    """The complete successor discovery payload, generated offline."""
    return build_provider_observed_discovery_plan(
        discovery_version=SUCCESSOR_DISCOVERY_VERSION,
        plan_identity=SUCCESSOR_DISCOVERY_PLAN_IDENTITY,
        h1_first_requested_from=successor_h1_requested_from(),
    )


def _granularity(request):
    return request["canonical_request"]["granularity"]


def _instrument(request):
    return request["canonical_request"]["instrument"]


def staged_discovery_membership(plan=None):
    """Derive the ordered, disjoint 1 + 5 + 126 execution stages from the plan.

    The canary is the extended first H1 window of one instrument; Gate 8D1 is
    the equivalent window for the other five; Gate 8D2 is everything else. All
    three are content-addressed by logical discovery key and ordered by the
    plan's own ordinals, so nothing is duplicated by hand.
    """
    plan = plan or build_successor_discovery_plan()
    requests = sorted(plan["requests"], key=lambda item: item["ordinal"])
    first_h1 = [
        item
        for item in requests
        if _granularity(item) == "H1"
        and item["canonical_request"]["from"] == SUCCESSOR_H1_REQUESTED_FROM
    ]
    if len(first_h1) != len(INSTRUMENTS):
        raise ValueError("the successor plan must extend one first H1 window per instrument")
    canary = [item for item in first_h1 if _instrument(item) == CANARY_INSTRUMENT]
    if len(canary) != 1:
        raise ValueError("the successor canary instrument must appear exactly once")
    cross = [item for item in first_h1 if _instrument(item) != CANARY_INSTRUMENT]
    staged_keys = {item["logical_discovery_key"] for item in first_h1}
    remainder = [item for item in requests if item["logical_discovery_key"] not in staged_keys]

    stages = {
        STAGE_CANARY: canary,
        STAGE_CROSS_INSTRUMENT: cross,
        STAGE_REMAINDER: remainder,
    }
    membership = {
        stage: [
            {
                "ordinal": item["ordinal"],
                "instrument": _instrument(item),
                "granularity": _granularity(item),
                "requested_from": item["canonical_request"]["from"],
                "requested_to": item["canonical_request"]["to"],
                "canonical_request_sha256": item["canonical_request_sha256"],
                "logical_discovery_key": item["logical_discovery_key"],
            }
            for item in items
        ]
        for stage, items in stages.items()
    }
    verify_staged_membership(membership, plan)
    return membership


def verify_staged_membership(membership, plan):
    """The stages must be disjoint, complete, ordered and exactly 1 + 5 + 126."""
    counts = {stage: len(items) for stage, items in membership.items()}
    if counts != EXPECTED_STAGE_COUNTS:
        raise ValueError(f"successor staging must be {EXPECTED_STAGE_COUNTS}, found {counts}")
    keys = [
        item["logical_discovery_key"]
        for stage in EXPECTED_STAGE_COUNTS
        for item in membership[stage]
    ]
    if len(set(keys)) != len(keys):
        raise ValueError("successor staging repeats a chunk")
    if set(keys) != {item["logical_discovery_key"] for item in plan["requests"]}:
        raise ValueError("successor staging does not cover the plan exactly once")
    for stage, items in membership.items():
        ordinals = [item["ordinal"] for item in items]
        if ordinals != sorted(ordinals):
            raise ValueError(f"successor stage {stage} is not ordered by plan ordinal")
    return counts


def verify_successor_plan_shape(plan=None):
    """Structural proof that the successor extends without re-cutting."""
    plan = plan or build_successor_discovery_plan()
    requests = plan["requests"]
    if (
        plan["declared_chunk_count"] != EXPECTED_CHUNK_COUNT
        or len(requests) != EXPECTED_CHUNK_COUNT
    ):
        raise ValueError("the successor plan must declare exactly 132 chunks")
    by_granularity = {}
    per_instrument = {}
    for item in requests:
        granularity, instrument = _granularity(item), _instrument(item)
        by_granularity[granularity] = by_granularity.get(granularity, 0) + 1
        per_instrument.setdefault(instrument, {})
        per_instrument[instrument][granularity] = per_instrument[instrument].get(granularity, 0) + 1
    if by_granularity != EXPECTED_GRANULARITY_CHUNKS:
        raise ValueError(f"successor granularity counts are {by_granularity}")
    if set(per_instrument) != set(INSTRUMENTS) or any(
        counts != EXPECTED_INSTRUMENT_CHUNKS for counts in per_instrument.values()
    ):
        raise ValueError("every instrument requires 1 D, 20 H1 and 1 W successor chunks")
    ordinals = [item["ordinal"] for item in requests]
    if ordinals != list(range(1, EXPECTED_CHUNK_COUNT + 1)):
        raise ValueError("successor ordinals must be dense, unique and one-based")
    return {"granularity_chunks": by_granularity, "instrument_chunks": EXPECTED_INSTRUMENT_CHUNKS}


def successor_ranges(plan=None):
    """The governed per-granularity request bounds the successor declares."""
    plan = plan or build_successor_discovery_plan()
    ranges = {}
    for item in plan["requests"]:
        granularity = _granularity(item)
        request = item["canonical_request"]
        bounds = ranges.setdefault(granularity, {"from": request["from"], "to": request["to"]})
        bounds["from"] = min(bounds["from"], request["from"])
        bounds["to"] = max(bounds["to"], request["to"])
    return ranges


def gate8b_authorization_path():
    return (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "strategy"
        / "failed-break"
        / "v1"
        / ARTIFACT_NAME
    )


def build_gate8b_authorization():
    """The deterministic authorization body, derived only from governed inputs."""
    plan = build_successor_discovery_plan()
    predecessor = build_provider_observed_discovery_plan(
        discovery_version=DISCOVERY_V2_VERSION,
        plan_identity=DISCOVERY_V2_PLAN_IDENTITY,
    )
    if predecessor["plan_sha256"] != DISCOVERY_V2_PLAN_SHA256:
        raise ValueError("the accepted predecessor discovery plan no longer reconstructs")
    shape = verify_successor_plan_shape(plan)
    membership = staged_discovery_membership(plan)
    body = {
        "schema": ARTIFACT_SCHEMA,
        "authorized_baseline_commit": AUTHORIZED_BASELINE_COMMIT,
        "design_report_sha256": DESIGN_REPORT_DIGEST,
        "predecessor_discovery_plan_identity": DISCOVERY_V2_PLAN_IDENTITY,
        "predecessor_discovery_plan_version": DISCOVERY_V2_VERSION,
        "predecessor_discovery_plan_sha256": DISCOVERY_V2_PLAN_SHA256,
        "predecessor_request_manifest_sha256": DISCOVERY_V2_MANIFEST_SHA256,
        "predecessor_global_semantic_inventory_sha256": GLOBAL_SEMANTIC_INVENTORY_SHA256,
        "predecessor_completion_summary_sha256": DISCOVERY_COMPLETION_SUMMARY_SHA256,
        "predecessor_registration_configuration_sha256": (
            PREDECESSOR_REGISTRATION_CONFIGURATION_SHA256
        ),
        "predecessor_registration_report_sha256": PREDECESSOR_REGISTRATION_REPORT_SHA256,
        "successor_discovery_plan_identity": SUCCESSOR_DISCOVERY_PLAN_IDENTITY,
        "successor_discovery_plan_version": SUCCESSOR_DISCOVERY_VERSION,
        "successor_discovery_plan_sha256": plan["plan_sha256"],
        "successor_request_manifest_sha256": plan["canonical_request_manifest_sha256"],
        "successor_h1_requested_from": SUCCESSOR_H1_REQUESTED_FROM,
        "successor_ranges": successor_ranges(plan),
        "successor_chunk_count": EXPECTED_CHUNK_COUNT,
        "successor_granularity_chunks": shape["granularity_chunks"],
        "successor_instrument_chunks": shape["instrument_chunks"],
        "staged_execution": membership,
        "staged_execution_counts": dict(EXPECTED_STAGE_COUNTS),
        "max_attempts_per_chunk": MAX_ATTEMPTS_PER_CHUNK,
        "expected_attempt_count": EXPECTED_ATTEMPT_COUNT,
        "automatic_retry_permitted": False,
        "required_h1_warmup_observations": REQUIRED_H1_WARMUP_OBSERVATIONS,
        "warmup_acceptance_rule": WARMUP_ACCEPTANCE_RULE,
        "calendar_exclusion_list": None,
        "strategy_outputs_consulted": False,
        "returns_consulted": False,
        "authorization_scope": AUTHORIZATION_SCOPE,
    }
    return {**body, "authorization_sha256": canonical_hash(body)}


def canonical_authorization_bytes(authorization=None):
    """The canonical JSON encoding this artifact is committed as."""
    authorization = authorization or build_gate8b_authorization()
    return json.dumps(authorization, sort_keys=True, separators=(",", ":")).encode()


def load_committed_gate8b_authorization(*, expected_file_sha256=None):
    """The committed artifact, accepted only when it is byte-for-byte the
    deterministic regeneration of the governed inputs.

    Enforcement here is Python byte comparison of the committed file. It is not
    a database guarantee: no PostgreSQL predicate compares this digest, and
    Gate 8B installs no migration. A future migration's operative authority is
    its own embedded plan SHA, range and state-transition constants; an artifact
    digest recorded beside them is catalog provenance only.
    """
    expected = build_gate8b_authorization()
    encoded = canonical_authorization_bytes(expected)
    path = gate8b_authorization_path()
    committed = path.read_bytes()
    if committed != encoded:
        raise ValueError("committed successor discovery authorization does not reconstruct")
    digest = hashlib.sha256(committed).hexdigest()
    if expected_file_sha256 is not None and digest != expected_file_sha256:
        raise ValueError(f"committed artifact {path.name} does not match its governed pin")
    if expected["authorization_sha256"] != canonical_hash(
        {key: value for key, value in expected.items() if key != "authorization_sha256"}
    ):
        raise ValueError("successor authorization self-hash does not verify")
    return expected
