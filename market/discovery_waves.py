"""Gate 4 wave-manifest tooling for provider-observed discovery.

The manifest is deterministic and secret-free: it derives entirely from the
frozen v2 replacement plan plus the recorded canary semantic-inventory hash,
covers exactly the 131 remaining chunks in canonical plan-ordinal order, and
carries an ordered-manifest SHA-256 over its chunk list.
"""

from market.historical_discovery import (
    CANARY_V2_INSTRUMENT,
    CANARY_V2_LOGICAL_KEY,
    build_replacement_discovery_plan,
    canonical_hash,
)

WAVE_MANIFEST_SCHEMA_IDENTITY = "phase-2b1r-gate4-wave-manifest-v1"
# Wave 1 covers every D and W chunk plus the first H1 chunk of each
# instrument other than the completed canary's (17 chunks); later waves take
# the remaining chunks in ordinal order in fixed bounded groups of this size,
# proposed for approval.
PROPOSED_LATER_WAVE_SIZE = 24
REMAINING_CHUNK_COUNT = 131


def build_wave_manifest(canary_semantic_inventory_sha256):
    plan = build_replacement_discovery_plan()
    remaining = [
        item for item in plan["requests"] if item["logical_discovery_key"] != CANARY_V2_LOGICAL_KEY
    ]
    first_h1_ordinals = {}
    for item in remaining:
        request = item["canonical_request"]
        if request["granularity"] != "H1":
            continue
        instrument = request["instrument"]
        if instrument == CANARY_V2_INSTRUMENT:
            # The canary instrument's H1 series already has its governed
            # first chunk; its remaining H1 chunks join the later waves.
            continue
        if instrument not in first_h1_ordinals:
            first_h1_ordinals[instrument] = item["ordinal"]
    wave_one_ordinals = {
        item["ordinal"]
        for item in remaining
        if item["canonical_request"]["granularity"] in {"D", "W"}
    } | set(first_h1_ordinals.values())
    later = [item for item in remaining if item["ordinal"] not in wave_one_ordinals]
    wave_numbers = {}
    for position, item in enumerate(later):
        wave_numbers[item["ordinal"]] = 2 + position // PROPOSED_LATER_WAVE_SIZE
    chunks = []
    for item in remaining:
        request = item["canonical_request"]
        chunks.append(
            {
                "wave_number": (
                    1 if item["ordinal"] in wave_one_ordinals else wave_numbers[item["ordinal"]]
                ),
                "ordinal": item["ordinal"],
                "logical_key": item["logical_discovery_key"],
                "instrument": request["instrument"],
                "granularity": request["granularity"],
                "requested_from": request["from"],
                "requested_to": request["to"],
                "canonical_request_sha256": item["canonical_request_sha256"],
            }
        )
    body = {
        "schema_identity": WAVE_MANIFEST_SCHEMA_IDENTITY,
        "v2_plan_sha256": plan["plan_sha256"],
        "v2_manifest_sha256": plan["canonical_request_manifest_sha256"],
        "canary_semantic_inventory_sha256": canary_semantic_inventory_sha256,
        "proposed_later_wave_size": PROPOSED_LATER_WAVE_SIZE,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }
    return {**body, "ordered_manifest_sha256": canonical_hash(chunks)}
