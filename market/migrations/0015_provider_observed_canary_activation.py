from importlib import import_module

from django.db import migrations

# Full portable fingerprints of the migration 0014 supersession governance
# this activation modifies, captured from a catalog migrated exactly through
# 0014 with the same fingerprint queries that migration's preflight uses.
REQUIRED_0014_FUNCTIONS = {
    "market_discovery_plan_xact_lock": ("plan_key bigint", "049915d1c7640a273f7c1946d90c272a"),
    "market_discovery_supersession_reject_mutation": ("", "ffdd7694b355279f9caf69aa15c00db9"),
    "market_discovery_supersession_reject_truncate": ("", "e5a8bd59d73d9862ca49fc22828920c1"),
    "market_reject_superseded_discovery_write": ("", "fe19b61f518d5c04b6971ebcaf3a8720"),
    "market_validate_discovery_supersession": ("", "915337e93db3e0a76a21f31c35ecab6c"),
}
REQUIRED_0014_TRIGGERS = {
    (
        "market_historicaldiscoveryapproval",
        "market_discovery_00_superseded_approval",
    ): "273a644811076df930135fa1429378f9",
    (
        "market_historicaldiscoveryattempt",
        "market_discovery_00_superseded_attempt",
    ): "b649bf76c7a525ce23271f1861174ea4",
    (
        "market_historicaldiscoverychunk",
        "market_discovery_00_superseded_chunk",
    ): "cc92aaf8e8bbd691c77fe6d83f07d634",
    (
        "market_historicaldiscoveryplan",
        "market_discovery_00_superseded_plan",
    ): "b0c14c39a6b6a30c573ed8ffc3e5c65d",
    (
        "market_historicaldiscoveryregistration",
        "market_discovery_00_superseded_registration",
    ): "82dd7a13041425f6500e759928a8b0bf",
    (
        "market_historicaldiscoverysupersession",
        "market_discovery_supersession_immutable",
    ): "6e292f862fee0f85f35ab93ee3fdef25",
    (
        "market_historicaldiscoverysupersession",
        "market_discovery_supersession_no_truncate",
    ): "043492933102938635a8d13a0131716d",
    (
        "market_historicaldiscoverysupersession",
        "market_discovery_supersession_validate",
    ): "52fcad0a7b208c7fd9d1deb3c0cf1f95",
}
ACTIVATION_FUNCTION = "market_validate_replacement_canary_attempt"
# Verbatim pg_proc.prosrc of the 0014 market_reject_superseded_discovery_write
# body, restored byte-identically by the empty reversal.
REJECT_WRITE_0014_PROSRC = r"""
        DECLARE plan_key bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key:=NEW.id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoverychunk' THEN
            plan_key:=NEW.plan_id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
            SELECT plan_id INTO STRICT plan_key FROM market_historicaldiscoverychunk
              WHERE id=NEW.chunk_id;
          ELSE
            plan_key:=NEW.plan_id;
          END IF;
          PERFORM market_discovery_plan_xact_lock(plan_key);
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE superseded_plan_id=plan_key)
          THEN RAISE EXCEPTION 'superseded discovery plans reject new writes'; END IF;
          IF TG_TABLE_NAME='market_historicaldiscoveryattempt'
             AND EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                        WHERE replacement_plan_id=plan_key)
          THEN RAISE EXCEPTION
            'supersession replacement plans reject attempts until governed activation';
          END IF;
          RETURN NEW;
        END """


def _governance():
    return import_module("market.migrations.0014_historical_discovery_supersession")


def preflight_canary_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    governance = _governance()
    problems = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('market_historicaldiscoverysupersession')")
        if cursor.fetchone()[0] is None:
            problems.append("supersession table from migration 0014 is missing")
        cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0014_FUNCTIONS)])
        found_functions = {}
        for name, identity_arguments, fingerprint in cursor.fetchall():
            found_functions.setdefault(name, []).append((identity_arguments, fingerprint))
        for name, expected in sorted(REQUIRED_0014_FUNCTIONS.items()):
            candidates = found_functions.get(name, [])
            if not candidates:
                problems.append(f"required 0014 function {name} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0014 function {name} has ambiguous overloads")
            elif candidates[0] != tuple(expected):
                problems.append(f"required 0014 function {name} does not match its 0014 definition")
        cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
        found_triggers = {}
        for table, name, fingerprint in cursor.fetchall():
            found_triggers.setdefault((table, name), []).append(fingerprint)
        for (table, name), expected in sorted(REQUIRED_0014_TRIGGERS.items()):
            candidates = found_triggers.get((table, name), [])
            if not candidates:
                problems.append(f"required 0014 trigger {name} on {table} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0014 trigger {name} on {table} is ambiguous")
            elif candidates[0] != expected:
                problems.append(
                    f"required 0014 trigger {name} on {table} does not match its 0014 definition"
                )
        cursor.execute(
            """SELECT count(*) FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = current_schema() AND p.proname = %s""",
            [ACTIVATION_FUNCTION],
        )
        if cursor.fetchone()[0] != 0:
            problems.append(f"unexpected pre-existing function {ACTIVATION_FUNCTION}")
    if problems:
        raise RuntimeError(
            "migration 0015 preflight rejected the current catalog: " + "; ".join(problems)
        )


def install_canary_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        r"""
        CREATE FUNCTION market_validate_replacement_canary_attempt(
          plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer,
          new_idempotency_key text, new_ingestion_run_id bigint) RETURNS void AS $$
        DECLARE plan record; chunk record; supersession record;
        BEGIN
          SELECT * INTO STRICT plan FROM market_historicaldiscoveryplan WHERE id=plan_key;
          SELECT * INTO STRICT chunk FROM market_historicaldiscoverychunk
            WHERE id=attempt_chunk_id;
          SELECT * INTO STRICT supersession FROM market_historicaldiscoverysupersession
            WHERE replacement_plan_id=plan_key;
          IF plan.version<>'phase-2b1r-discovery-v2'
             OR plan.identity<>'failed-break-phase-2b1r-discovery-plan-v2'
             OR plan.sha256<>
                '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
             OR market_sha256(plan.payload)<>
                '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
             OR plan.canonical_request_manifest_sha256<>
                '04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR market_sha256(plan.payload->'requests')<>
                '04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR market_sha256(plan.canonical_request_manifest)<>
                '04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR plan.sealed_at IS NOT NULL
             OR supersession.replacement_plan_sha256<>plan.sha256
             OR supersession.reason_code<>'PROVIDER_REQUEST_BOUND_UNSAFE'
             OR supersession.sha256<>market_sha256(supersession.payload)
             OR chunk.plan_id<>plan_key
             OR chunk.ordinal<>2
             OR chunk.granularity<>'H1'
             OR chunk.logical_key<>
                '63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d'
             OR chunk.canonical_request_sha256<>
                '3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1'
             OR chunk.requested_from<>timestamptz '2009-12-31 15:00:00+00'
             OR chunk.requested_to<>timestamptz '2010-06-16 07:00:00+00'
             OR (SELECT i.code FROM market_instrument i
                 WHERE i.id=chunk.instrument_id)<>'AUD_USD'
             OR new_attempt_number<>1
             OR new_idempotency_key<>'historical-discovery-attempt:'
                ||'63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d:1'
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt a
                       JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                       WHERE c.plan_id=plan_key)
             OR EXISTS(SELECT 1 FROM market_ingestionrun r
                       WHERE r.parameters->>'purpose'=
                             'provider_timestamp_inventory_discovery'
                         AND r.status='running' AND r.id<>new_ingestion_run_id)
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryapproval ap
                       WHERE ap.plan_id=plan_key)
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryregistration rg
                       WHERE rg.plan_id=plan_key)
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
        END $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION market_reject_superseded_discovery_write()
        RETURNS trigger AS $$
        DECLARE plan_key bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key:=NEW.id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoverychunk' THEN
            plan_key:=NEW.plan_id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
            SELECT plan_id INTO STRICT plan_key FROM market_historicaldiscoverychunk
              WHERE id=NEW.chunk_id;
          ELSE
            plan_key:=NEW.plan_id;
          END IF;
          PERFORM market_discovery_plan_xact_lock(plan_key);
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE superseded_plan_id=plan_key)
          THEN RAISE EXCEPTION 'superseded discovery plans reject new writes'; END IF;
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE replacement_plan_id=plan_key) THEN
            IF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
              PERFORM market_validate_replacement_canary_attempt(
                plan_key, NEW.chunk_id, NEW.attempt_number, NEW.idempotency_key,
                NEW.ingestion_run_id);
            ELSIF TG_TABLE_NAME IN ('market_historicaldiscoveryapproval',
                                    'market_historicaldiscoveryregistration') THEN
              RAISE EXCEPTION
                'supersession replacement plans reject approval until governed activation';
            ELSIF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
              RAISE EXCEPTION
                'supersession replacement plans reject sealing until governed activation';
            END IF;
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        """
    )


def remove_canary_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FROM market_historicaldiscoveryattempt a
               JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
               JOIN market_historicaldiscoverysupersession s
                 ON s.replacement_plan_id=c.plan_id"""
        )
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("replacement discovery attempts prohibit canary activation reversal")
    schema_editor.execute(
        "CREATE OR REPLACE FUNCTION market_reject_superseded_discovery_write() "
        "RETURNS trigger AS $governed$" + REJECT_WRITE_0014_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;"
    )
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS market_validate_replacement_canary_attempt("
        "bigint, bigint, integer, text, bigint);"
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("market", "0014_historical_discovery_supersession"),
    ]

    operations = [
        migrations.RunPython(preflight_canary_activation, migrations.RunPython.noop),
        migrations.RunPython(install_canary_activation, remove_canary_activation),
    ]
