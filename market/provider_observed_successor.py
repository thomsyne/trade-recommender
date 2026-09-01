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

# The governed digest of the committed artifact file, pinned in code so that a
# coordinated edit to both this module's constants and the artifact still fails:
# regeneration would agree with the file, but neither would agree with this.
AUTHORIZATION_FILE_SHA256 = "f128467b9c1e0bd77bac75bafd30e5fa4c8949d887b209a9930f1a93b91a4a02"

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


# Operational note (Gate 8B' review finding, informational).
#
# The governed snapshot digest used by the operational gates hashes
# ``to_jsonb(row)`` over governed tables, and ``to_jsonb(timestamptz)`` renders
# in the *session* time zone. The same unchanged research data therefore hashes
# to 358826f1... under a psql session in America/Toronto and to 2c45f3c3...
# under a Django session in UTC.
#
# 358826f1... is meaningful only under the session settings its original
# snapshot method used. Future operational gates must set the PostgreSQL
# session time zone explicitly, and report it, on both sides of any snapshot
# comparison. No repository helper computes this digest, so there is nothing
# here to correct in production code; this is an operational rule.


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


def _verify_committed_authorization(*, expected_file_sha256):
    """The four checks, in the order that makes each one meaningful.

    The digest is required, not optional: a caller cannot reach this without
    naming the bytes it expects. Only tests pass anything but the governed
    constant, and they do so to reach a layer the constant would shadow.
    """
    path = gate8b_authorization_path()
    # 1-2: the committed bytes, against a digest pinned in code. A digest taken
    # from the artifact under inspection would prove nothing, so this value
    # never comes from the file.
    committed = path.read_bytes()
    digest = hashlib.sha256(committed).hexdigest()
    if digest != expected_file_sha256:
        raise ValueError(f"committed artifact {path.name} does not match its governed pin")
    # 3-6: the committed document's own self-hash, recomputed from the committed
    # body rather than from anything this process just generated.
    try:
        document = json.loads(committed)
    except ValueError as error:
        raise ValueError("committed successor discovery authorization is not valid JSON") from error
    claimed = document.get("authorization_sha256")
    body = {key: value for key, value in document.items() if key != "authorization_sha256"}
    if claimed != canonical_hash(body):
        raise ValueError("successor authorization self-hash does not verify")
    # 7-8: and only then, that the committed content is what production code
    # deterministically regenerates.
    expected = build_gate8b_authorization()
    if committed != canonical_authorization_bytes(expected):
        raise ValueError("committed successor discovery authorization does not reconstruct")
    return expected


def load_committed_gate8b_authorization():
    """The committed artifact, accepted only when its bytes hash to the governed
    file digest, its own embedded self-hash verifies, and its content is the
    deterministic regeneration of the governed inputs.

    Enforcement here is Python byte comparison of the committed file. It is not
    a database guarantee: no PostgreSQL predicate compares this digest, and
    Gate 8B installs no migration. A future migration's operative authority is
    its own embedded plan SHA, range and state-transition constants; an artifact
    digest recorded beside them is catalog provenance only.
    """
    return _verify_committed_authorization(expected_file_sha256=AUTHORIZATION_FILE_SHA256)


PREDECESSOR_H1_REQUESTED_FROM = "2009-12-31T15:00:00Z"
MINIMUM_EARLIER_OBSERVATIONS = 6

# Terminal run states that represent an unsuccessful discovery attempt. The
# discovery services only ever record "failed"; "quarantined" is carried for
# completeness because it is the acquisition path's terminal failure and must
# never be mistaken for a success. "running" is not terminal and "succeeded" is
# terminal but successful, so neither belongs here.
TERMINAL_FAILURE_STATUSES = ("failed", "quarantined")


def successor_stage(chunk):
    """Which staged gate a successor chunk belongs to, or None for any chunk
    outside the governed successor plan."""
    plan = chunk.plan
    if plan.sha256 != build_successor_discovery_plan()["plan_sha256"]:
        return None
    extended = (
        chunk.granularity == "H1"
        and chunk.canonical_request.get("from") == SUCCESSOR_H1_REQUESTED_FROM
    )
    if extended and chunk.instrument.code == CANARY_INSTRUMENT:
        return STAGE_CANARY
    return STAGE_CROSS_INSTRUMENT if extended else STAGE_REMAINDER


def _ready_first_h1(plan, *, canary_only):
    """Governed first-H1 chunks whose attempt 1 succeeded and whose sealed
    inventory carries at least six observations earlier than the predecessor's
    H1 start. Counted from sealed observations only: a closure contributes
    nothing, and an observed timestamp is never discarded for a calendar label."""
    from market.historical_discovery import parse_timestamp
    from market.models import HistoricalTimestampObservation, IngestionRun

    boundary = parse_timestamp(PREDECESSOR_H1_REQUESTED_FROM)
    ready = 0
    for chunk in plan.chunks.select_related("instrument").filter(granularity="H1"):
        if chunk.canonical_request.get("from") != SUCCESSOR_H1_REQUESTED_FROM:
            continue
        if canary_only and chunk.instrument.code != CANARY_INSTRUMENT:
            continue
        attempt = chunk.attempts.filter(
            attempt_number=1, ingestion_run__status=IngestionRun.Status.SUCCEEDED
        ).first()
        inventory = getattr(chunk, "inventory", None)
        if attempt is None or inventory is None:
            continue
        earlier = HistoricalTimestampObservation.objects.filter(
            inventory=inventory, timestamp__lt=boundary
        ).count()
        if earlier >= MINIMUM_EARLIER_OBSERVATIONS:
            ready += 1
    return ready


def _successor_runs(plan, *statuses):
    """Runs in the given states reached relationally: successor plan → its
    chunks → their attempts → those attempts' own runs. Never inferred from an
    event name, error string or artifact field."""
    from market.models import IngestionRun

    return IngestionRun.objects.filter(
        historical_discovery_attempt__chunk__plan=plan, status__in=statuses
    )


def assert_successor_attempt_permitted(chunk):
    """Fail closed, before any provider client exists, unless this chunk is the
    stage the governed sequence has actually opened."""
    from market.models import IngestionRun
    from market.services import DatasetQualityError

    stage = successor_stage(chunk)
    if stage is None:
        return
    plan = chunk.plan
    if plan.chunks.count() != EXPECTED_CHUNK_COUNT:
        raise DatasetQualityError("successor discovery requires its complete authorized plan")
    if chunk.attempts.exists():
        raise DatasetQualityError("successor discovery permits only attempt 1 for each chunk")
    if _successor_runs(plan, IngestionRun.Status.RUNNING).exists():
        raise DatasetQualityError("a successor discovery attempt is already running")
    # A failure ends the plan, not merely its own chunk: attempt 2 is prohibited,
    # so the 132-chunk plan can never complete, and every further request would
    # be spent on a plan that can never be sealed or registered.
    if _successor_runs(plan, *TERMINAL_FAILURE_STATUSES).exists():
        raise DatasetQualityError(
            "a failed successor discovery attempt permanently stops this plan"
        )
    if stage == STAGE_CANARY:
        return
    if stage == STAGE_CROSS_INSTRUMENT:
        if _ready_first_h1(plan, canary_only=True) != 1:
            raise DatasetQualityError(
                "gate 8D1 requires the governed canary to have succeeded with at least"
                " six additional eligible observations"
            )
        return
    if _ready_first_h1(plan, canary_only=False) != len(INSTRUMENTS):
        raise DatasetQualityError(
            "gate 8D2 requires all six governed first-H1 inventories to have succeeded"
            " with at least six additional eligible observations each"
        )


def _attempted_logical_keys(plan):
    """Logical keys of successor chunks that already carry an attempt.

    Attempt 2 is prohibited, so any attempt closes its chunk permanently
    whatever its run reached: succeeded, failed, quarantined or still running.
    Scoped relationally to this plan's own chunks, so a predecessor v1 or v2
    attempt can never remove a successor key.
    """
    from market.models import HistoricalDiscoveryAttempt

    return set(
        HistoricalDiscoveryAttempt.objects.filter(chunk__plan=plan).values_list(
            "chunk__logical_key", flat=True
        )
    )


# Execution states the read-only interface reports. Exactly one holds at a time.
STATUS_NOT_MATERIALIZED = "not_materialized"
STATUS_BLOCKED = "blocked_by_failed_attempt"
STATUS_ATTEMPT_IN_PROGRESS = "attempt_in_progress"
STATUS_COMPLETE = "complete"
STATUS_OPEN = "open"
STATUS_NO_ELIGIBLE_CHUNK = "no_eligible_chunk"


def successor_readiness(plan=None):
    """Read-only report of which successor chunks may actually be executed now.

    Permission is derived from both the governed stage the sequence has
    unlocked and each chunk's own attempt lineage, because the database admits
    an attempt only when both allow it. A chunk that already has an attempt is
    never reported as executable, so a completed or failed key can never
    reappear, and once all 132 chunks have been attempted the plan reports
    successful completion rather than naming a stage it can no longer open.

    Performs no write and constructs no provider client.
    """
    from market.models import HistoricalDiscoveryPlan, IngestionRun

    payload = plan or build_successor_discovery_plan()
    membership = staged_discovery_membership(payload)
    row = HistoricalDiscoveryPlan.objects.filter(sha256=payload["plan_sha256"]).first()
    if row is None:
        return {
            "successor_plan_sha256": payload["plan_sha256"],
            "materialized": False,
            "execution_status": STATUS_NOT_MATERIALIZED,
            "complete": False,
            "permitted_stage": None,
            "permitted_logical_keys": [],
            "note": "the successor discovery plan has not been materialized",
        }
    canary_ready = _ready_first_h1(row, canary_only=True) == 1
    all_ready = _ready_first_h1(row, canary_only=False) == len(INSTRUMENTS)
    blocked = _successor_runs(row, *TERMINAL_FAILURE_STATUSES).exists()
    running = _successor_runs(row, IngestionRun.Status.RUNNING).exists()
    stage = (
        STAGE_REMAINDER if all_ready else (STAGE_CROSS_INSTRUMENT if canary_ready else STAGE_CANARY)
    )
    chunk_count = row.chunks.count()
    attempted = _attempted_logical_keys(row)
    # The single-flight rule refuses every chunk while an attempt is running, so
    # nothing may be offered as available until that attempt reaches a terminal
    # state.
    permitted = (
        []
        if blocked or running
        else [
            item["logical_discovery_key"]
            for item in membership[stage]
            if item["logical_discovery_key"] not in attempted
        ]
    )
    complete = (
        not blocked
        and not running
        and chunk_count == EXPECTED_CHUNK_COUNT
        and len(attempted) == EXPECTED_CHUNK_COUNT
    )
    if blocked:
        status = STATUS_BLOCKED
    elif running:
        status = STATUS_ATTEMPT_IN_PROGRESS
    elif complete:
        status = STATUS_COMPLETE
    elif permitted:
        status = STATUS_OPEN
    else:
        status = STATUS_NO_ELIGIBLE_CHUNK
    return {
        "successor_plan_sha256": payload["plan_sha256"],
        "materialized": True,
        "chunks": chunk_count,
        "attempted_chunks": len(attempted),
        "blocked_by_failed_attempt": blocked,
        "execution_status": status,
        "complete": complete,
        # Named only while it actually has an executable key, so the field can
        # never imply that a completed or blocked stage may still be run.
        "permitted_stage": stage if permitted else None,
        "permitted_logical_keys": permitted,
        "canary_prerequisite_met": canary_ready,
        "cross_instrument_prerequisite_met": all_ready,
    }
