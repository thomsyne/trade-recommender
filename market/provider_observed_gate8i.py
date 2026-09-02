"""Gate 8I: final successor dataset acceptance and registration authority.

This module is read-only.  It binds the accepted successor acquisition to a
decomposed operational snapshot, the predecessor overlap, the warm-up extension,
and the existing registration service.  It never constructs a provider client.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from market.historical_acquisition import stable_hash
from market.historical_discovery import canonical_hash
from market.provider_observed_gate8e import (
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATASET_MANIFEST_SHA256,
)
from market.provider_observed_gate8g import (
    ARTIFACT_PATH as GATE8F_ARTIFACT_PATH,
)
from market.provider_observed_gate8g import (
    GATE8F_OUTCOME_ARTIFACT_SHA256,
    GATE8G_ORDERED_MANIFEST_SHA256,
    SUCCESSOR_ACQUISITION_PLAN_SHA256,
    load_committed_gate8f_outcome,
    successor_gate8g_readiness,
)
from market.provider_observed_outcome import (
    SNAPSHOT_SECTIONS,
    gate8d3_outcome_path,
    load_committed_gate8d3_outcome,
    section_hash_sql,
)
from market.provider_observed_registration import (
    REPLACEMENT_REGISTRATION_IDENTITY,
    verify_registration_readiness,
)
from market.services import DatasetQualityError

ARTIFACT_SCHEMA = "phase-2b1r-gate8i-final-dataset-acceptance-v1"
ARTIFACT_NAME = "phase-2b1r-gate8i-final-dataset-acceptance.json"
ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "strategy"
    / "failed-break"
    / "v1"
    / ARTIFACT_NAME
)

AUTHORIZED_BASELINE_COMMIT = "51398bf6b0744b09f9a8fa3b467fb9e3051a56df"
DECOMPOSED_SNAPSHOT_CONVENTION = "phase-2b1r-decomposed-operational-snapshot-v2"
SNAPSHOT_TIME_ZONE = "America/Toronto"
CANDLE_SHARD_SIZE = 50_000

GATE8D3_ARTIFACT_SHA256 = "b13fe357e5c2dec3450a6fc15cf755d6a940e6b83af8592cfdedaa9cc74156c5"
GATE8D3_OUTCOME_SHA256 = "30c11d7470bd63003ebc71a71da04e754d85d70671050f819a869cf985e63692"
GATE8F_OUTCOME_SHA256 = "1abf67c7c0bf31441634285beb5e832766418c69eb026f59de7abbb47d1fe5d6"
POST_GATE8G_SECTIONED_SNAPSHOT_SHA256 = (
    "89696f4a1bb0a02adc2cf69b18387b8293abe8bf39f9208ea62fa7b4e2be40ec"
)
PRE_GATE8G_EXCLUSION_SNAPSHOT_SHA256 = (
    "5c4bb9e6420653aa479ee9ae3bd61065762668f4d52ee883a46751306c364c79"
)

PREDECESSOR_CONTRACT_SHA256 = "60b603f26662bfc8faa4373177690bc0ae23820b914815f47c11d8367c07f7bf"
PREDECESSOR_PLAN_SHA256 = "f0be516c732d775ce57fd98a39a7dd7df917d4eaa2c9c0ffd2fc7028d9a23528"
PREDECESSOR_DATASET_MANIFEST_SHA256 = (
    "9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54"
)
PREDECESSOR_CANDLE_COUNT = 364_953
PREDECESSOR_CANDLE_KEY_HASH = "5f7850a317808688066ead6f46f7085e05e840d0a0c73b1ab4fc56f792ede5ea"
PREDECESSOR_CANDLE_PAYLOAD_HASH = "218bb6fb8c456a02bb10193179bed9b93e4be5a71da10ff9aee028e4e41c0d10"

SUCCESSOR_CANDLE_COUNT = 365_055
SUCCESSOR_GRANULARITY_TOTALS = {"D": 17_412, "H1": 344_817, "W": 2_826}
SUCCESSOR_LOGICAL_CHUNK_SET_HASH = (
    "b850362c83f5f2b65ab2b1a920fb2394182ff384d202cc5a938fbd1358a9f92d"
)
SUCCESSOR_SUCCESSFUL_ATTEMPT_SET_HASH = (
    "ff30e8bb6ccf48a10751d650662107c237bb7cbffc873c0037e9daec02382eb0"
)
SUCCESSOR_INGESTION_MANIFEST_SET_HASH = (
    "be8902096245d9af8191c3ef789219207e85c290abbcece5299a8528e579c0a4"
)
SUCCESSOR_CANDLE_KEY_HASH = "03e9ecfc4270c06dcfff9e62fb2ca2115f1abbe352a753040272808f1969dbb9"
SUCCESSOR_CANDLE_PAYLOAD_HASH = "3bc9449a854fbc7b46b7cc2798182fd70cb1ca4ec356d87bd74ed41835512c2a"
EXTENSION_CANDLE_COUNT = 102
EXTENSION_PER_INSTRUMENT = 17
EXTENSION_CANDLE_KEY_HASH = "39c4d393ed5bacc1465e5fc994e68d2982ab200a0f43c01af8426b3892d8959e"
EXTENSION_CANDLE_PAYLOAD_HASH = "47c08140801bcab5c7ee47b68aa8bb6db21363b3b0ac6606e618d13aedadf02b"
REQUIRED_H1_WARMUP = 14
PREDECESSOR_H1_WARMUP = 8
SUCCESSOR_H1_EXTENSION = 17
COMBINED_H1_WARMUP = 25

# Filled from the credential-free disposable restore, then pinned into the
# canonical final-acceptance artifact.  No persistent database is consulted by
# artifact loading.
DECOMPOSED_SNAPSHOT = json.loads(
    r"""{"convention":"phase-2b1r-decomposed-operational-snapshot-v2","section_order":["discovery_plans","discovery_chunks","discovery_attempts","runs","inventories","observations","provider_evidence","audits","approval","registration","supersession","contracts","acquisition_plans","acquisition_chunks","acquisition_attempts","manifests","candles","datasets","dataset_registrations","strategy_definitions","strategy_versions","strategy_manifests","schedules"],"sections":{"acquisition_attempts":{"mode":"single-jsonb","row_count":272,"sha256":"b40d07b2fe808ee10248a673810fbd09cc346cc7a0b6cf25f410250de6a955ce"},"acquisition_chunks":{"mode":"single-jsonb","row_count":348,"sha256":"dab93fd91239e781eb4cc0370140858eb5e7979d80463572f3834f9c44bd47e8"},"acquisition_plans":{"mode":"single-jsonb","row_count":3,"sha256":"4c97a201e829e9675de1728bb7e147e790f4245e3c5bb5a3793f4bb8c5af714e"},"approval":{"mode":"single-jsonb","row_count":2,"sha256":"cb1bd204dbb20b3876cb1f77c585824b7f663d94e0116ea28c1bc4062b269fde"},"audits":{"mode":"single-jsonb","row_count":801,"sha256":"2f3dc780fdc36fb04b8d110c465c81bb2a7025776f57a7b7816827af1f8b19ac"},"candles":{"mode":"keyset-sharded-jsonb","order_by":"id","row_count":732834,"shard_size":50000,"shards":[{"first_id":1,"last_id":50000,"ordinal":1,"row_count":50000,"sha256":"7e402fff94402b2ddc2045793f98c865bd845a34bec9fcc28252d8cc4d6bceb9"},{"first_id":50001,"last_id":100000,"ordinal":2,"row_count":50000,"sha256":"a6cf128371a01edcd960db896933df7bb66ad802bc5886712638b230f774d972"},{"first_id":100001,"last_id":150000,"ordinal":3,"row_count":50000,"sha256":"7b4fc8601a73f1b26d25393df2ecb62eb3d94c8354f28ddaa52b30db409e6be2"},{"first_id":150001,"last_id":200000,"ordinal":4,"row_count":50000,"sha256":"65e736c8b2d00b476416903b5e89fc0ef24a057d82679653cc25dbc771eec89f"},{"first_id":200001,"last_id":250000,"ordinal":5,"row_count":50000,"sha256":"81f9f4da779c93b3b5659e848e94774c57012a378a7d4d0452393e5b70073d5b"},{"first_id":250001,"last_id":300000,"ordinal":6,"row_count":50000,"sha256":"cb89351879c4d09566f191d9d0e5aaa98f6369c4b28b31dd0efbe566e347ab43"},{"first_id":300001,"last_id":350000,"ordinal":7,"row_count":50000,"sha256":"62928457e2acae8e1966f8f130a7e4b7ce38f91b4d17a3e57082129eb50a32ac"},{"first_id":350001,"last_id":400000,"ordinal":8,"row_count":50000,"sha256":"373f41bab7f3cebf3fe7b7c95839739338acf1d324a205234f087a5902beef45"},{"first_id":400001,"last_id":450000,"ordinal":9,"row_count":50000,"sha256":"23e2f3d053b2481c2e8dba76a63886bfe2f45149b928be59256ecdf59663f271"},{"first_id":450001,"last_id":500000,"ordinal":10,"row_count":50000,"sha256":"8e72a382645dfb6b79a6c0196c2a25c72f24edef48ed38c2a48f9265321ac6cf"},{"first_id":500001,"last_id":550000,"ordinal":11,"row_count":50000,"sha256":"6ef8a4994a69ea7b98542ada2912920113b6f093a46d83c465a30f2b5a888b6e"},{"first_id":550001,"last_id":600000,"ordinal":12,"row_count":50000,"sha256":"84860b5622076398a06855bd58a7a71d7d09d0d32f3b415814d96c311200fcc6"},{"first_id":600001,"last_id":650000,"ordinal":13,"row_count":50000,"sha256":"2d8954cccd089e0535c70c8d56bd58d9898d6b6a9ee0b4963509020a3da3aeb0"},{"first_id":650001,"last_id":700000,"ordinal":14,"row_count":50000,"sha256":"66a9a1e2306e20da46d5d0811ef491f77633c3cf3f10424a7aac00cd50837375"},{"first_id":700001,"last_id":732834,"ordinal":15,"row_count":32834,"sha256":"0b1b07480816873a8b9726a420653abaf66711979f57f6fee06e00a9b864c006"}]},"contracts":{"mode":"single-jsonb","row_count":2,"sha256":"af5640a7ce403e6c68855086bde35915c5145d5e8c3a64dd39a65d39efb2de81"},"dataset_registrations":{"mode":"single-jsonb","row_count":1,"sha256":"413ec081400896d9759ea49c181139b83c52cdbec8d325076052a6168f92897e"},"datasets":{"mode":"single-jsonb","row_count":3,"sha256":"999d65542563b01048d8c6c17b2a21c6f15667981a00b9a94d609099391bfc55"},"discovery_attempts":{"mode":"single-jsonb","row_count":266,"sha256":"ea1fb59cf77268ad0108f1a02e6227bfff977723ab1b23d9828db78b13432833"},"discovery_chunks":{"mode":"single-jsonb","row_count":348,"sha256":"f1e3a99a208ad54c3030b683116d07326a261b1abb01196d02aeffe34f8e8af1"},"discovery_plans":{"mode":"single-jsonb","row_count":3,"sha256":"e79efd5e715ba40ba6bbcbdfbac6799aef789927b319f85f7436e6ad2d574297"},"inventories":{"mode":"single-jsonb","row_count":264,"sha256":"cbd7ada20daf3bbd4cd72c762ab370fa109cf7aa0c101391c50f119fdee72d4b"},"manifests":{"mode":"single-jsonb","row_count":270,"sha256":"78da603a9b9d7a8a06f54064e184a2ae931088e6a66faff9ae85f80fcca346de"},"observations":{"mode":"single-jsonb","row_count":730008,"sha256":"d7b3372da764ad6efdf1f1946751f86859d64ff6b4f6a9b6173473e19a47394f"},"provider_evidence":{"mode":"single-jsonb","row_count":266,"sha256":"663e406373ded0c84523f4b865e26d14b8453a22f50b9679d121fa5524d1293b"},"registration":{"mode":"single-jsonb","row_count":2,"sha256":"45e0384d76fff3228715d69a22cba3827a3a3fd437512c13b22ecdd8c0a54e37"},"runs":{"mode":"single-jsonb","row_count":538,"sha256":"8efef17810e8d5234aba3220083cde4bb50aed63ae3926432e6bc60aee03b1a5"},"schedules":{"mode":"single-jsonb","row_count":0,"sha256":null},"strategy_definitions":{"mode":"single-jsonb","row_count":1,"sha256":"2d6f82de7bfca1153c5b2a32c9bf3e1b3ee0ad738f16d998c7fc638badbaffe4"},"strategy_manifests":{"mode":"single-jsonb","row_count":1,"sha256":"a1f7b910779783bfc77f1b01ccba57710212c57d34b16a8799046212ae0d857a"},"strategy_versions":{"mode":"single-jsonb","row_count":1,"sha256":"ec29ed2f8b0f51e67b556621d54c033761d265ddf412bc8b3313d5c87b370bdb"},"supersession":{"mode":"single-jsonb","row_count":1,"sha256":"6c78d2b52a1bc592653d7d3051b6677fc09e35e55b7d6f51d8bd8a64e06fd28b"}},"session_time_zone":"America/Toronto","snapshot_sha256":"357f9dfc4b3adb21d8b38418376d5feb6978338c66fb09ba669cc60845acff5a"}"""
)
FINAL_ACCEPTANCE_ARTIFACT_SHA256 = (
    "5ea57f6f2b8b1c487a9638652f1d6ec1568f8297604629f8d360471c6c45e297"
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _single_section(cursor, name, table):
    cursor.execute(f"SELECT count(*) FROM {table}")
    count = cursor.fetchone()[0]
    cursor.execute(section_hash_sql(name))
    return {"mode": "single-jsonb", "row_count": count, "sha256": cursor.fetchone()[0]}


def _candle_shards(cursor, *, shard_size=CANDLE_SHARD_SIZE):
    if shard_size < 1:
        raise ValueError("candle shard size must be positive")
    shards = []
    last_id = 0
    while True:
        cursor.execute(
            """
            WITH shard AS (
              SELECT cd.* FROM market_candle cd
               WHERE cd.id > %s ORDER BY cd.id LIMIT %s
            )
            SELECT count(*), min(id), max(id),
                   market_sha256(jsonb_agg(to_jsonb(shard) ORDER BY id))
              FROM shard
            """,
            [last_id, shard_size],
        )
        count, first_id, final_id, digest = cursor.fetchone()
        if count == 0:
            break
        shards.append(
            {
                "ordinal": len(shards) + 1,
                "row_count": count,
                "first_id": first_id,
                "last_id": final_id,
                "sha256": digest,
            }
        )
        last_id = final_id
    return {
        "mode": "keyset-sharded-jsonb",
        "order_by": "id",
        "shard_size": shard_size,
        "row_count": sum(item["row_count"] for item in shards),
        "shards": shards,
    }


def decomposed_operational_snapshot(cursor, *, candle_shard_size=CANDLE_SHARD_SIZE):
    """Hash the established 23 sections while bounding every JSONB aggregate.

    Non-candle sections retain the established formula.  Candles are split by
    ordered keyset pages; each page is independently canonicalized and hashed,
    then the complete ordered shard manifest is bound by the outer digest.
    """
    cursor.execute("SET LOCAL TIME ZONE %s", [SNAPSHOT_TIME_ZONE])
    sections = {}
    for name, table, _alias, _order in SNAPSHOT_SECTIONS:
        sections[name] = (
            _candle_shards(cursor, shard_size=candle_shard_size)
            if name == "candles"
            else _single_section(cursor, name, table)
        )
    body = {
        "convention": DECOMPOSED_SNAPSHOT_CONVENTION,
        "session_time_zone": SNAPSHOT_TIME_ZONE,
        "section_order": [name for name, _table, _alias, _order in SNAPSHOT_SECTIONS],
        "sections": sections,
    }
    return {**body, "snapshot_sha256": canonical_hash(body)}


def decomposed_snapshot_summary(snapshot):
    candles = snapshot["sections"]["candles"]
    return {
        "convention": snapshot["convention"],
        "session_time_zone": snapshot["session_time_zone"],
        "section_count": len(snapshot["section_order"]),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "candles": {
            "mode": candles["mode"],
            "order_by": candles["order_by"],
            "row_count": candles["row_count"],
            "shard_size": candles["shard_size"],
            "shard_count": len(candles["shards"]),
            "shard_manifest_sha256": canonical_hash(candles["shards"]),
        },
    }


def current_decomposed_operational_snapshot():
    """Compute the bounded snapshot in one consistent database transaction."""
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return decomposed_operational_snapshot(cursor)


def build_gate8i_acceptance():
    gate8d3 = load_committed_gate8d3_outcome()
    gate8f = load_committed_gate8f_outcome()
    if (
        _file_sha256(gate8d3_outcome_path()) != GATE8D3_ARTIFACT_SHA256
        or gate8d3["outcome_sha256"] != GATE8D3_OUTCOME_SHA256
        or _file_sha256(GATE8F_ARTIFACT_PATH) != GATE8F_OUTCOME_ARTIFACT_SHA256
        or gate8f["outcome_sha256"] != GATE8F_OUTCOME_SHA256
    ):
        raise ValueError("accepted predecessor artifacts do not match their pins")
    if not DECOMPOSED_SNAPSHOT:
        raise ValueError("decomposed final snapshot is not pinned")
    warmup = gate8d3["warmup_proof"]
    if len(warmup) != 6 or any(
        item["earlier_completed_observations"] != SUCCESSOR_H1_EXTENSION
        or item["predecessor_warmup_observations"] != PREDECESSOR_H1_WARMUP
        or item["combined_completed_warmup_observations"] != COMBINED_H1_WARMUP
        or item["required_warmup_observations"] != REQUIRED_H1_WARMUP
        for item in warmup
    ):
        raise ValueError("accepted warm-up proof does not reconstruct")
    body = {
        "schema": ARTIFACT_SCHEMA,
        "authorized_baseline_commit": AUTHORIZED_BASELINE_COMMIT,
        "registration_identity": REPLACEMENT_REGISTRATION_IDENTITY,
        "data_contract_sha256": SUCCESSOR_CONTRACT_SHA256,
        "replacement_plan_sha256": SUCCESSOR_ACQUISITION_PLAN_SHA256,
        "replacement_dataset_manifest_sha256": SUCCESSOR_DATASET_MANIFEST_SHA256,
        "global_semantic_inventory_sha256": gate8f["successor"]["global_semantic_inventory_sha256"],
        "chunk_count": 132,
        "successful_attempt_count": 132,
        "ingestion_manifest_count": 132,
        "candle_count": SUCCESSOR_CANDLE_COUNT,
        "granularity_candle_totals": dict(sorted(SUCCESSOR_GRANULARITY_TOTALS.items())),
        "logical_chunk_set_hash": SUCCESSOR_LOGICAL_CHUNK_SET_HASH,
        "successful_attempt_set_hash": SUCCESSOR_SUCCESSFUL_ATTEMPT_SET_HASH,
        "ingestion_manifest_set_hash": SUCCESSOR_INGESTION_MANIFEST_SET_HASH,
        "candle_key_hash": SUCCESSOR_CANDLE_KEY_HASH,
        "candle_payload_hash": SUCCESSOR_CANDLE_PAYLOAD_HASH,
        "final_acquisition_snapshot_sha256": DECOMPOSED_SNAPSHOT["snapshot_sha256"],
        "operational_snapshots": {
            "post_gate8g_sectioned_streamed_sha256": POST_GATE8G_SECTIONED_SNAPSHOT_SHA256,
            "pre_gate8g_exclusion_sha256": PRE_GATE8G_EXCLUSION_SNAPSHOT_SHA256,
            "decomposed": decomposed_snapshot_summary(DECOMPOSED_SNAPSHOT),
        },
        "accepted_lineage": {
            "gate8d3_artifact_sha256": GATE8D3_ARTIFACT_SHA256,
            "gate8d3_outcome_sha256": GATE8D3_OUTCOME_SHA256,
            "gate8f_artifact_sha256": GATE8F_OUTCOME_ARTIFACT_SHA256,
            "gate8f_outcome_sha256": GATE8F_OUTCOME_SHA256,
            "gate8g_ordered_manifest_sha256": GATE8G_ORDERED_MANIFEST_SHA256,
        },
        "predecessor_overlap": {
            "predecessor_data_contract_sha256": PREDECESSOR_CONTRACT_SHA256,
            "predecessor_plan_sha256": PREDECESSOR_PLAN_SHA256,
            "predecessor_dataset_manifest_sha256": PREDECESSOR_DATASET_MANIFEST_SHA256,
            "predecessor_candle_count": PREDECESSOR_CANDLE_COUNT,
            "identical_overlap_count": PREDECESSOR_CANDLE_COUNT,
            "changed_overlap_count": 0,
            "predecessor_only_count": 0,
            "candle_key_hash": PREDECESSOR_CANDLE_KEY_HASH,
            "candle_payload_hash": PREDECESSOR_CANDLE_PAYLOAD_HASH,
        },
        "successor_extension": {
            "candle_count": EXTENSION_CANDLE_COUNT,
            "granularity": "H1",
            "per_instrument_count": EXTENSION_PER_INSTRUMENT,
            "first_timestamp": "2009-12-30T22:00:00+00:00",
            "last_timestamp": "2009-12-31T14:00:00+00:00",
            "candle_key_hash": EXTENSION_CANDLE_KEY_HASH,
            "candle_payload_hash": EXTENSION_CANDLE_PAYLOAD_HASH,
        },
        "warmup_proof": warmup,
        "authorization_scope": (
            "authorizes only a later explicit registration and immutable sealing transition for"
            " the accepted successor dataset; it does not itself register or seal and does not"
            " authorize provider access, discovery, acquisition, S0, S1, returns or backtesting"
        ),
    }
    return {**body, "authorization_sha256": stable_hash(body)}


def load_committed_gate8i_acceptance():
    if not FINAL_ACCEPTANCE_ARTIFACT_SHA256:
        raise ValueError("final acceptance artifact file pin is not configured")
    committed = ARTIFACT_PATH.read_bytes()
    if hashlib.sha256(committed).hexdigest() != FINAL_ACCEPTANCE_ARTIFACT_SHA256:
        raise ValueError("committed final acceptance artifact does not match its file pin")
    expected = build_gate8i_acceptance()
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    if committed != encoded:
        raise ValueError("committed final acceptance artifact does not reconstruct")
    return expected


def _successor_comparison(dataset, authorization):
    from django.db import connection

    from market.models import DatasetRegistration, DatasetVersion

    predecessors = list(
        DatasetVersion.objects.filter(manifest_sha256=PREDECESSOR_DATASET_MANIFEST_SHA256)
    )
    if len(predecessors) != 1:
        raise DatasetQualityError("accepted predecessor dataset does not resolve exactly")
    predecessor = predecessors[0]
    registration = DatasetRegistration.objects.filter(dataset_version=predecessor).first()
    if (
        registration is None
        or registration.candle_key_hash != PREDECESSOR_CANDLE_KEY_HASH
        or registration.candle_payload_hash != PREDECESSOR_CANDLE_PAYLOAD_HASH
    ):
        raise DatasetQualityError("accepted predecessor registration does not reconstruct")

    fields = (
        "complete",
        "volume",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    )
    left = ",".join(f"s.{field}" for field in fields)
    right = ",".join(f"p.{field}" for field in fields)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT count(*) FILTER (WHERE p.id IS NOT NULL),
                   count(*) FILTER (WHERE p.id IS NULL),
                   count(*) FILTER (WHERE p.id IS NOT NULL
                     AND ({left}) IS DISTINCT FROM ({right}))
              FROM market_candle s
              LEFT JOIN market_candle p
                ON p.dataset_version_id=%s
               AND p.instrument_id=s.instrument_id
               AND p.granularity=s.granularity AND p.timestamp=s.timestamp
             WHERE s.dataset_version_id=%s
            """,
            [predecessor.pk, dataset.pk],
        )
        overlap, extension, changed = cursor.fetchone()
        cursor.execute(
            """
            SELECT count(*) FROM market_candle p
              LEFT JOIN market_candle s
                ON s.dataset_version_id=%s
               AND s.instrument_id=p.instrument_id
               AND s.granularity=p.granularity AND s.timestamp=p.timestamp
             WHERE p.dataset_version_id=%s AND s.id IS NULL
            """,
            [dataset.pk, predecessor.pk],
        )
        predecessor_only = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT i.code,s.granularity,s.timestamp,s.complete,s.volume,
                   s.bid_open,s.bid_high,s.bid_low,s.bid_close,
                   s.ask_open,s.ask_high,s.ask_low,s.ask_close
              FROM market_candle s JOIN market_instrument i ON i.id=s.instrument_id
              LEFT JOIN market_candle p
                ON p.dataset_version_id=%s
               AND p.instrument_id=s.instrument_id
               AND p.granularity=s.granularity AND p.timestamp=s.timestamp
             WHERE s.dataset_version_id=%s AND p.id IS NULL
             ORDER BY i.code,s.granularity,s.timestamp
            """,
            [predecessor.pk, dataset.pk],
        )
        extension_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT i.code,
              (SELECT count(*) FROM market_candle s
                WHERE s.dataset_version_id=%s AND s.instrument_id=i.id
                  AND s.granularity='H1' AND s.complete
                  AND s.timestamp<'2009-12-31T15:00:00Z'::timestamptz
                  AND s.timestamp<='2010-01-01T04:00:00Z'::timestamptz),
              (SELECT count(*) FROM market_candle p
                WHERE p.dataset_version_id=%s AND p.instrument_id=i.id
                  AND p.granularity='H1' AND p.complete
                  AND p.timestamp<='2010-01-01T04:00:00Z'::timestamptz)
              FROM market_instrument i
             WHERE i.code=ANY(%s) ORDER BY i.code
            """,
            [
                dataset.pk,
                predecessor.pk,
                [item["instrument"] for item in authorization["warmup_proof"]],
            ],
        )
        warmup = cursor.fetchall()

    keys = hashlib.sha256()
    payloads = hashlib.sha256()
    by_instrument = {}
    for code, granularity, timestamp, complete, volume, *prices in extension_rows:
        stamp = timestamp.isoformat()
        key = [code, granularity, stamp]
        payload = key + [complete, volume, *[format(value, ".6f") for value in prices]]
        keys.update(json.dumps(key, separators=(",", ":")).encode())
        payloads.update(json.dumps(payload, separators=(",", ":")).encode())
        by_instrument[code] = by_instrument.get(code, 0) + 1
    observed = {
        "overlap": overlap,
        "extension": extension,
        "changed": changed,
        "predecessor_only": predecessor_only,
        "extension_key_hash": keys.hexdigest(),
        "extension_payload_hash": payloads.hexdigest(),
        "extension_by_instrument": by_instrument,
        "warmup": {code: [earlier, prior, earlier + prior] for code, earlier, prior in warmup},
    }
    expected_instruments = {item["instrument"] for item in authorization["warmup_proof"]}
    if (
        overlap != authorization["predecessor_overlap"]["identical_overlap_count"]
        or extension != authorization["successor_extension"]["candle_count"]
        or changed != 0
        or predecessor_only != 0
        or keys.hexdigest() != authorization["successor_extension"]["candle_key_hash"]
        or payloads.hexdigest() != authorization["successor_extension"]["candle_payload_hash"]
        or by_instrument != {code: EXTENSION_PER_INSTRUMENT for code in expected_instruments}
        or observed["warmup"]
        != {
            code: [SUCCESSOR_H1_EXTENSION, PREDECESSOR_H1_WARMUP, COMBINED_H1_WARMUP]
            for code in expected_instruments
        }
    ):
        raise DatasetQualityError("successor overlap, extension or warm-up evidence disagrees")
    return observed


def verify_successor_registration_readiness(dataset, plan, *, authorization=None):
    """Fail closed over the final artifact before the existing registration path."""
    authorization = authorization or load_committed_gate8i_acceptance()
    if (
        plan.sha256 != SUCCESSOR_ACQUISITION_PLAN_SHA256
        or dataset.manifest_sha256 != SUCCESSOR_DATASET_MANIFEST_SHA256
        or plan.data_contract_id is None
        or plan.data_contract.sha256 != SUCCESSOR_CONTRACT_SHA256
    ):
        raise DatasetQualityError("successor registration identity does not match Gate 8I")
    readiness = successor_gate8g_readiness()
    if not readiness.complete or readiness.ready_keys or readiness.blocked_reason is not None:
        raise DatasetQualityError("successor acquisition is not complete and accepted")
    base = verify_registration_readiness(dataset, plan, authorization=authorization)
    comparison = _successor_comparison(dataset, authorization)
    snapshot = current_decomposed_operational_snapshot()
    if (
        decomposed_snapshot_summary(snapshot)
        != authorization["operational_snapshots"]["decomposed"]
    ):
        raise DatasetQualityError("live decomposed snapshot disagrees with final acceptance")
    return {**base, "comparison": comparison, "decomposed_snapshot": snapshot}


def is_successor_registration(dataset, plan):
    markers = (
        plan.sha256 == SUCCESSOR_ACQUISITION_PLAN_SHA256,
        dataset.manifest_sha256 == SUCCESSOR_DATASET_MANIFEST_SHA256,
        plan.data_contract_id is not None
        and plan.data_contract.sha256 == SUCCESSOR_CONTRACT_SHA256,
    )
    if any(markers) and not all(markers):
        raise DatasetQualityError("partial successor registration identity is refused")
    return all(markers)
