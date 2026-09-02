"""Gate 8I: authorize only the accepted successor dataset registration.

The existing provider-observed registration validator remains the sealing
mechanism.  This migration adds a successor-only acceptance prelude to that
body; its predecessor branch is otherwise byte-identical to migration 0022.
"""

from importlib import import_module

from django.db import migrations

SUCCESSOR_CONTRACT_SHA256 = "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
SUCCESSOR_PLAN_SHA256 = "44dc82b2f20975e34e34e30ca7a709fff059ed14fa7457aaa26da4222d4df4cd"
SUCCESSOR_DATASET_MANIFEST_SHA256 = (
    "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
)
SUCCESSOR_GLOBAL_SEMANTIC_SHA256 = (
    "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
)
PREDECESSOR_DATASET_MANIFEST_SHA256 = (
    "9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54"
)
FINAL_ACCEPTANCE_SHA256 = "ed68a01dc00d67b95de8720e0b8a85f1ee35603265daca1ec0cce28eac5b8905"
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

gate8g = import_module("market.migrations.0026_gate8g_successor_acquisition_activation")
gate7c = import_module("market.migrations.0022_provider_observed_registration_validator_correction")

PRIOR_REGISTRATION_PROSRC = gate7c.CORRECTED_REPLACEMENT_REGISTRATION_PROSRC
_INSERTION = """          SELECT * INTO STRICT contract FROM market_historicaldatacontract
            WHERE id=plan.data_contract_id;
"""
SUCCESSOR_AUTHORITY_PROSRC = r"""          -- accepted artifact: ed68a01dc00d67b95de8720e0b8a85f1ee35603265daca1ec0cce28eac5b8905
          IF contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN
            IF contract.sha256<>'d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c'
               OR contract.global_semantic_inventory_sha256<>
                    'f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427'
               OR plan.sha256<>'44dc82b2f20975e34e34e30ca7a709fff059ed14fa7457aaa26da4222d4df4cd'
               OR dataset.manifest_sha256<>
                    '11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014'
               OR reg.logical_chunk_set_hash<>
                    'b850362c83f5f2b65ab2b1a920fb2394182ff384d202cc5a938fbd1358a9f92d'
               OR reg.successful_attempt_set_hash<>
                    'ff30e8bb6ccf48a10751d650662107c237bb7cbffc873c0037e9daec02382eb0'
               OR reg.ingestion_manifest_set_hash<>
                    'be8902096245d9af8191c3ef789219207e85c290abbcece5299a8528e579c0a4'
               OR reg.candle_key_hash<>
                    '03e9ecfc4270c06dcfff9e62fb2ca2115f1abbe352a753040272808f1969dbb9'
               OR reg.candle_payload_hash<>
                    '3bc9449a854fbc7b46b7cc2798182fd70cb1ca4ec356d87bd74ed41835512c2a'
               OR (SELECT count(*) FROM market_historicalingestionchunk c
                     WHERE c.plan_id=plan.id AND c.dataset_version_id=dataset.id)<>132
               OR (SELECT count(*) FROM market_historicalingestionattempt a
                     JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
                     JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
                    WHERE c.plan_id=plan.id AND c.dataset_version_id=dataset.id
                      AND a.attempt_number=1 AND r.status='succeeded')<>132
               OR (SELECT count(*) FROM market_candle c
                     WHERE c.dataset_version_id=dataset.id)<>365055
               OR (SELECT count(*) FROM market_candle s
                     JOIN market_datasetversion predecessor ON predecessor.manifest_sha256=
                       '9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54'
                     JOIN market_candle p ON p.dataset_version_id=predecessor.id
                      AND p.instrument_id=s.instrument_id AND p.granularity=s.granularity
                      AND p.timestamp=s.timestamp
                    WHERE s.dataset_version_id=dataset.id
                      AND (s.complete,s.volume,s.bid_open,s.bid_high,s.bid_low,s.bid_close,
                           s.ask_open,s.ask_high,s.ask_low,s.ask_close)
                          IS NOT DISTINCT FROM
                          (p.complete,p.volume,p.bid_open,p.bid_high,p.bid_low,p.bid_close,
                           p.ask_open,p.ask_high,p.ask_low,p.ask_close))<>364953
               OR (SELECT count(*) FROM market_candle s
                     LEFT JOIN market_candle p ON p.dataset_version_id=(SELECT id
                       FROM market_datasetversion WHERE manifest_sha256=
                       '9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54')
                      AND p.instrument_id=s.instrument_id AND p.granularity=s.granularity
                      AND p.timestamp=s.timestamp
                    WHERE s.dataset_version_id=dataset.id AND p.id IS NULL)<>102
               OR (SELECT count(*) FROM market_candle p
                     LEFT JOIN market_candle s ON s.dataset_version_id=dataset.id
                      AND s.instrument_id=p.instrument_id AND s.granularity=p.granularity
                      AND s.timestamp=p.timestamp
                    WHERE p.dataset_version_id=(SELECT id FROM market_datasetversion
                      WHERE manifest_sha256=
                       '9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54')
                      AND s.id IS NULL)<>0
               OR (SELECT count(*) FROM (
                     SELECT i.id
                       FROM market_instrument i
                      WHERE i.code=ANY(ARRAY['AUD_USD','EUR_GBP','EUR_USD',
                                             'GBP_USD','USD_CAD','USD_JPY'])
                        AND (SELECT count(*) FROM market_candle s
                              WHERE s.dataset_version_id=dataset.id
                                AND s.instrument_id=i.id AND s.granularity='H1' AND s.complete
                                AND s.timestamp<'2009-12-31T15:00:00Z'::timestamptz
                                AND s.timestamp<='2010-01-01T04:00:00Z'::timestamptz)=17
                        AND (SELECT count(*) FROM market_candle p
                              WHERE p.dataset_version_id=(SELECT id
                                FROM market_datasetversion WHERE manifest_sha256=
                       '9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54')
                                AND p.instrument_id=i.id AND p.granularity='H1' AND p.complete
                                AND p.timestamp<='2010-01-01T04:00:00Z'::timestamptz)=8
                   ) warmed)<>6
            THEN RAISE EXCEPTION
              'successor dataset lacks accepted Gate 8I registration authority'; END IF;
          ELSIF contract.identity<>'oanda-ba-ny17-friday-provider-observed-v1' THEN
            RAISE EXCEPTION 'provider-observed dataset identity is not authorized';
          END IF;
"""
if PRIOR_REGISTRATION_PROSRC.count(_INSERTION) != 1:
    raise RuntimeError("migration 0022 registration body is not the reviewed predecessor")
GATE8I_REGISTRATION_PROSRC = PRIOR_REGISTRATION_PROSRC.replace(
    _INSERTION, _INSERTION + SUCCESSOR_AUTHORITY_PROSRC
)

REQUIRED_0026_FUNCTIONS = dict(gate8g.REQUIRED_0025_FUNCTIONS)
REQUIRED_0026_FUNCTIONS.update(
    {
        "market_validate_acquisition_canary": (
            "attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, "
            "new_run_id bigint",
            "16f42f453373684ee4f445f054edcb72",
        ),
        "market_verify_successor_canary_success": ("", "7d8eee69b7592795cf103d9fe5c5c033"),
    }
)
REQUIRED_0026_TRIGGERS = dict(gate8g.REQUIRED_0025_TRIGGERS)
if len(REQUIRED_0026_FUNCTIONS) != 57 or len(REQUIRED_0026_TRIGGERS) != 74:
    raise RuntimeError("migration 0026 governed catalog pin is incomplete")


def _require_0026_catalog(cursor):
    functions, triggers = gate8g._catalog(cursor)
    if set(functions) != set(REQUIRED_0026_FUNCTIONS):
        raise RuntimeError("Gate 8I requires the complete migration 0026 function catalog")
    if set(triggers) != set(REQUIRED_0026_TRIGGERS):
        raise RuntimeError("Gate 8I requires the complete migration 0026 trigger catalog")
    for name, expected in REQUIRED_0026_FUNCTIONS.items():
        if functions[name] != [expected]:
            raise RuntimeError(f"migration 0026 function {name} does not match its catalog pin")
    for key, expected in REQUIRED_0026_TRIGGERS.items():
        if triggers[key] != [expected]:
            raise RuntimeError(f"migration 0026 trigger {key[1]} does not match its catalog pin")
    if (
        gate8g._installed_body(cursor, "market_validate_replacement_registration")
        != PRIOR_REGISTRATION_PROSRC
    ):
        raise RuntimeError("installed registration validator is not the migration 0022 body")
    return functions, triggers


def _require_accepted_successor_state(cursor):
    cursor.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE r.status='succeeded'),
               count(*) FILTER (WHERE a.attempt_number<>1 OR r.status<>'succeeded'),
               coalesce(sum(r.stored_count),0)
          FROM market_historicalingestionattempt a
          JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
          JOIN market_historicaldatasetplan p ON p.id=c.plan_id
          JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
         WHERE p.sha256=%s
        """,
        [SUCCESSOR_PLAN_SHA256],
    )
    if cursor.fetchone() != (132, 132, 0, 365055):
        raise RuntimeError("Gate 8I requires the accepted complete successor acquisition")
    cursor.execute(
        """
        SELECT count(*) FROM market_datasetregistration reg
         JOIN market_datasetversion d ON d.id=reg.dataset_version_id
         WHERE d.manifest_sha256=%s
        """,
        [SUCCESSOR_DATASET_MANIFEST_SHA256],
    )
    if cursor.fetchone()[0] != 0:
        raise RuntimeError("successor dataset is already registered and sealed")


def _without_registration_validator(catalog):
    functions, triggers = catalog
    return (
        {
            name: rows
            for name, rows in functions.items()
            if name != "market_validate_replacement_registration"
        },
        triggers,
    )


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        before = _require_0026_catalog(cursor)
        _require_accepted_successor_state(cursor)
        untouched = _without_registration_validator(before)
        gate8g._install(
            cursor,
            "market_validate_replacement_registration(reg market_datasetregistration)",
            "void",
            GATE8I_REGISTRATION_PROSRC,
        )
        after = gate8g._catalog(cursor)
        if len(after[0]) != 57 or len(after[1]) != 74:
            raise RuntimeError("Gate 8I must replace exactly one function and no trigger")
        if _without_registration_validator(after) != untouched:
            raise RuntimeError("Gate 8I altered a governance object outside its exact delta")
        if (
            gate8g._installed_body(cursor, "market_validate_replacement_registration")
            != GATE8I_REGISTRATION_PROSRC
        ):
            raise RuntimeError("Gate 8I registration authority did not install exactly")


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM market_datasetregistration reg
             JOIN market_datasetversion d ON d.id=reg.dataset_version_id
             WHERE d.manifest_sha256=%s
            """,
            [SUCCESSOR_DATASET_MANIFEST_SHA256],
        )
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("successor registration and sealing evidence prohibits reversal")
        before = gate8g._catalog(cursor)
        if (
            gate8g._installed_body(cursor, "market_validate_replacement_registration")
            != GATE8I_REGISTRATION_PROSRC
        ):
            raise RuntimeError("installed registration validator is not the Gate 8I body")
        untouched = _without_registration_validator(before)
        gate8g._install(
            cursor,
            "market_validate_replacement_registration(reg market_datasetregistration)",
            "void",
            PRIOR_REGISTRATION_PROSRC,
        )
        restored = gate8g._catalog(cursor)
        if _without_registration_validator(restored) != untouched:
            raise RuntimeError("Gate 8I reversal altered an unrelated governance object")
        _require_0026_catalog(cursor)


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("market", "0026_gate8g_successor_acquisition_activation")]

    operations = [migrations.RunPython(forward, reverse)]
