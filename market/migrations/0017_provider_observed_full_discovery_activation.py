from importlib import import_module

from django.db import migrations

# Full portable fingerprints of the exact 0016-state governance this
# migration depends on, captured with the 0014 fingerprint queries from a
# catalog migrated exactly through 0016.
REQUIRED_0016_FUNCTIONS = {
    "market_discovery_plan_xact_lock": ("plan_key bigint", "049915d1c7640a273f7c1946d90c272a"),
    "market_discovery_structural_diagnostics_valid": (
        "diagnostics jsonb, fetched integer",
        "4a587767d6def1327aa0f65e2bc6d845",
    ),
    "market_discovery_supersession_reject_mutation": ("", "ffdd7694b355279f9caf69aa15c00db9"),
    "market_discovery_supersession_reject_truncate": ("", "e5a8bd59d73d9862ca49fc22828920c1"),
    "market_reject_superseded_discovery_write": ("", "26c4702c5c14f0f00816c67594a81584"),
    "market_validate_discovery_audit_insert": ("", "b3c77ca417a58f608d7a869547dd3782"),
    "market_validate_discovery_observation": ("", "7722c113c70b269f3df1e193d992ab09"),
    "market_validate_discovery_supersession": ("", "915337e93db3e0a76a21f31c35ecab6c"),
    "market_validate_replacement_canary_attempt": (
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, new_ingestion_run_id bigint",
        "aa3d3cb94d9b177800c738d1e22f2e22",
    ),
}
REQUIRED_0016_TRIGGERS = {
    ("market_auditevent", "market_discovery_audit_validate"): "40a061306928fdc23f5018034229acd1",
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
    (
        "market_historicaltimestampobservation",
        "market_discovery_observation_validate",
    ): "ab51c3031892cd203d5220471d9ee406",
}
# Verbatim pg_proc.prosrc of the 0016 canary activation function, restored
# byte-identically by the empty reversal.
CANARY_ACTIVATION_0016_PROSRC = r"""
        DECLARE plan record; chunk record; supersession record; governing record;
                governing_run record; governing_evidence record; failure_event record;
                attempt_total integer; failure_event_count integer;
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
             OR EXISTS(SELECT 1 FROM market_ingestionrun r
                       WHERE r.parameters->>'purpose'=
                             'provider_timestamp_inventory_discovery'
                         AND r.status='running' AND r.id<>new_ingestion_run_id)
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryapproval ap
                       WHERE ap.plan_id=plan_key)
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryregistration rg
                       WHERE rg.plan_id=plan_key)
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          SELECT count(*) INTO attempt_total FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            WHERE c.plan_id=plan_key;
          IF attempt_total<>1 THEN
            RAISE EXCEPTION 'replacement canary activation rejects this attempt';
          END IF;
          SELECT a.* INTO governing FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            WHERE c.plan_id=plan_key ORDER BY a.id LIMIT 1;
          SELECT * INTO STRICT governing_run FROM market_ingestionrun
            WHERE id=governing.ingestion_run_id;
          SELECT * INTO governing_evidence FROM market_historicaldiscoveryproviderevidence
            WHERE attempt_id=governing.id;
          SELECT count(*) INTO failure_event_count FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=governing.id::text
              AND audit.event_type='market.historical_discovery_failed';
          SELECT audit.* INTO failure_event FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=governing.id::text
              AND audit.event_type='market.historical_discovery_failed' LIMIT 1;
          IF governing.chunk_id<>attempt_chunk_id
             OR governing.attempt_number<>1
             OR governing.idempotency_key<>'historical-discovery-attempt:'
                ||'63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d:1'
             OR governing_run.status<>'failed'
             OR governing_run.failure_reason<>'DISCOVERY_STRUCTURE_INVALID'
             OR governing_run.fetched_count<>2932
             OR governing_run.stored_count<>0
             OR governing_run.rejected_count<>2932
             OR governing_run.finished_at IS NULL
             OR governing_evidence.id IS NULL
             OR governing_evidence.http_status<>200
             OR governing_evidence.http_method<>'GET'
             OR governing_evidence.environment<>'practice'
             OR governing_evidence.endpoint_identity<>
                'oanda-v20-practice:GET:/v3/instruments/AUD_USD/candles'
             OR governing_evidence.canonical_request_sha256<>
                '3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1'
             OR coalesce(governing_evidence.provider_request_id,'')=''
             OR governing_evidence.unavailable_fields<>'[]'::jsonb
             OR failure_event_count<>1
             OR EXISTS(SELECT 1 FROM market_auditevent success_audit
                       WHERE success_audit.subject_type='HistoricalDiscoveryAttempt'
                         AND success_audit.subject_id=governing.id::text
                         AND success_audit.event_type=
                             'market.historical_discovery_succeeded')
             OR failure_event.event_type IS DISTINCT FROM
                'market.historical_discovery_failed'
             OR failure_event.payload->>'event_sha256' IS DISTINCT FROM
                governing_evidence.terminal_event_sha256
             OR market_sha256(failure_event.payload-'event_sha256') IS DISTINCT FROM
                governing_evidence.terminal_event_sha256
             OR failure_event.payload->>'error_code' IS DISTINCT FROM
                'DISCOVERY_STRUCTURE_INVALID'
             OR failure_event.payload->>'stage' IS DISTINCT FROM 'response_validation'
             OR failure_event.payload->'diagnostics'->'issue_counts' IS DISTINCT FROM
                jsonb_build_object('timestamp_misaligned',106)
             OR EXISTS(SELECT 1 FROM market_historicaltimestampinventory inv
                       JOIN market_historicaldiscoverychunk c ON c.id=inv.chunk_id
                       WHERE c.plan_id=plan_key)
             OR new_attempt_number<>2
             OR new_idempotency_key<>'historical-discovery-attempt:'
                ||'63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d:2'
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
        END """
GATE4_ACTIVATION_PROSRC = r"""
        DECLARE plan record; chunk record; supersession record; canary record;
                att1 record; att1_run record; att1_evidence record; att1_event record;
                att2 record; att2_run record; att2_evidence record; att2_event record;
                inventory_row record; canary_attempts integer; observations_ok boolean;
                att1_failures integer; att1_successes integer;
                att2_failures integer; att2_successes integer;
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
             OR EXISTS(SELECT 1 FROM market_ingestionrun r
                       WHERE r.parameters->>'purpose'=
                             'provider_timestamp_inventory_discovery'
                         AND r.status='running' AND r.id<>new_ingestion_run_id)
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryapproval ap
                       WHERE ap.plan_id=plan_key)
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryregistration rg
                       WHERE rg.plan_id=plan_key)
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          SELECT c.* INTO canary FROM market_historicaldiscoverychunk c
            WHERE c.plan_id=plan_key AND c.logical_key=
              '63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d';
          IF canary.id IS NULL
             OR canary.ordinal<>2
             OR canary.granularity<>'H1'
             OR canary.canonical_request_sha256<>
                '3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1'
             OR canary.requested_from<>timestamptz '2009-12-31 15:00:00+00'
             OR canary.requested_to<>timestamptz '2010-06-16 07:00:00+00'
             OR (SELECT i.code FROM market_instrument i
                 WHERE i.id=canary.instrument_id)<>'AUD_USD'
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          SELECT count(*) INTO canary_attempts FROM market_historicaldiscoveryattempt
            WHERE chunk_id=canary.id;
          SELECT a.* INTO att1 FROM market_historicaldiscoveryattempt a
            WHERE a.chunk_id=canary.id AND a.attempt_number=1;
          SELECT a.* INTO att2 FROM market_historicaldiscoveryattempt a
            WHERE a.chunk_id=canary.id AND a.attempt_number=2;
          IF canary_attempts<>2 OR att1.id IS NULL OR att2.id IS NULL THEN
            RAISE EXCEPTION 'replacement canary activation rejects this attempt';
          END IF;
          SELECT * INTO STRICT att1_run FROM market_ingestionrun
            WHERE id=att1.ingestion_run_id;
          SELECT * INTO att1_evidence FROM market_historicaldiscoveryproviderevidence
            WHERE attempt_id=att1.id;
          SELECT count(*) INTO att1_failures FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=att1.id::text
              AND audit.event_type='market.historical_discovery_failed';
          SELECT count(*) INTO att1_successes FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=att1.id::text
              AND audit.event_type='market.historical_discovery_succeeded';
          SELECT audit.* INTO att1_event FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=att1.id::text
              AND audit.event_type='market.historical_discovery_failed' LIMIT 1;
          IF att1.idempotency_key<>'historical-discovery-attempt:'
             ||'63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d:1'
             OR att1_run.status<>'failed'
             OR att1_run.failure_reason<>'DISCOVERY_STRUCTURE_INVALID'
             OR att1_run.fetched_count<>2932
             OR att1_run.stored_count<>0
             OR att1_run.rejected_count<>2932
             OR att1_run.finished_at IS NULL
             OR att1_evidence.id IS NULL
             OR att1_evidence.http_status<>200
             OR att1_evidence.http_method<>'GET'
             OR att1_evidence.environment<>'practice'
             OR att1_evidence.endpoint_identity<>
                'oanda-v20-practice:GET:/v3/instruments/AUD_USD/candles'
             OR att1_evidence.canonical_request_sha256<>
                '3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1'
             OR coalesce(att1_evidence.provider_request_id,'')=''
             OR att1_evidence.unavailable_fields<>'[]'::jsonb
             OR att1_failures<>1 OR att1_successes<>0
             OR att1_event.payload->>'event_sha256' IS DISTINCT FROM
                att1_evidence.terminal_event_sha256
             OR market_sha256(att1_event.payload-'event_sha256') IS DISTINCT FROM
                att1_evidence.terminal_event_sha256
             OR att1_event.payload->>'error_code' IS DISTINCT FROM
                'DISCOVERY_STRUCTURE_INVALID'
             OR att1_event.payload->>'stage' IS DISTINCT FROM 'response_validation'
             OR att1_event.payload->'diagnostics'->'issue_counts' IS DISTINCT FROM
                jsonb_build_object('timestamp_misaligned',106)
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          SELECT * INTO STRICT att2_run FROM market_ingestionrun
            WHERE id=att2.ingestion_run_id;
          SELECT * INTO att2_evidence FROM market_historicaldiscoveryproviderevidence
            WHERE attempt_id=att2.id;
          SELECT count(*) INTO att2_failures FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=att2.id::text
              AND audit.event_type='market.historical_discovery_failed';
          SELECT count(*) INTO att2_successes FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=att2.id::text
              AND audit.event_type='market.historical_discovery_succeeded';
          SELECT audit.* INTO att2_event FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=att2.id::text
              AND audit.event_type='market.historical_discovery_succeeded' LIMIT 1;
          IF att2.idempotency_key<>'historical-discovery-attempt:'
             ||'63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d:2'
             OR att2_run.status<>'succeeded'
             OR att2_run.failure_reason<>''
             OR att2_run.fetched_count<>2932
             OR att2_run.stored_count<>2932
             OR att2_run.rejected_count<>0
             OR att2_run.finished_at IS NULL
             OR att2_evidence.id IS NULL
             OR att2_evidence.http_status<>200
             OR att2_evidence.http_method<>'GET'
             OR att2_evidence.environment<>'practice'
             OR att2_evidence.endpoint_identity<>
                'oanda-v20-practice:GET:/v3/instruments/AUD_USD/candles'
             OR att2_evidence.canonical_request_sha256<>
                '3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1'
             OR coalesce(att2_evidence.provider_request_id,'')=''
             OR att2_evidence.unavailable_fields<>'[]'::jsonb
             OR att2_successes<>1 OR att2_failures<>0
             OR att2_event.payload->>'event_sha256' IS DISTINCT FROM
                att2_evidence.terminal_event_sha256
             OR market_sha256(att2_event.payload-'event_sha256') IS DISTINCT FROM
                att2_evidence.terminal_event_sha256
             OR att2_evidence.operational_evidence_sha256<>market_sha256(
                jsonb_build_object(
                  'logical_discovery_key',canary.logical_key,
                  'attempt_number',att2.attempt_number,
                  'attempt_idempotency_key',att2.idempotency_key,
                  'run_id',att2_run.id,
                  'run_request_manifest_hash',att2_run.request_manifest_hash,
                  'canonical_request_sha256',att2_evidence.canonical_request_sha256,
                  'endpoint_identity',att2_evidence.endpoint_identity,
                  'environment',att2_evidence.environment,
                  'http_method',att2_evidence.http_method,
                  'http_status',att2_evidence.http_status,
                  'provider_request_id',att2_evidence.provider_request_id,
                  'unavailable_fields',att2_evidence.unavailable_fields,
                  'started_at',market_discovery_operational_timestamp(att2_run.started_at),
                  'finished_at',market_discovery_operational_timestamp(att2_run.finished_at),
                  'terminal_status',att2_run.status,
                  'failure_code',nullif(att2_run.failure_reason,''),
                  'terminal_event_sha256',att2_evidence.terminal_event_sha256))
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          SELECT inv.* INTO inventory_row FROM market_historicaltimestampinventory inv
            WHERE inv.chunk_id=canary.id;
          IF (SELECT count(*) FROM market_historicaltimestampinventory
              WHERE chunk_id=canary.id)<>1
             OR inventory_row.accepted_attempt_id<>att2.id
             OR inventory_row.observation_count<>2932
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          SELECT count(*)=2932 AND count(DISTINCT o.timestamp)=2932
                 AND bool_and(o.complete) AND bool_and(o.bid_present)
                 AND bool_and(o.ask_present) AND bool_and(o.volume>=0)
                 AND bool_and(o.timestamp>=canary.requested_from
                              AND o.timestamp<canary.requested_to)
                 AND bool_and(date_trunc('hour',o.timestamp AT TIME ZONE 'UTC')
                              =o.timestamp AT TIME ZONE 'UTC')
            INTO observations_ok FROM market_historicaltimestampobservation o
            WHERE o.inventory_id=inventory_row.id;
          IF observations_ok IS DISTINCT FROM true
             OR inventory_row.timestamp_set_sha256<>market_sha256(
                (SELECT jsonb_agg(market_discovery_timestamp(o.timestamp)
                                  ORDER BY o.timestamp)
                   FROM market_historicaltimestampobservation o
                  WHERE o.inventory_id=inventory_row.id))
             OR inventory_row.structural_observation_sha256<>market_sha256(
                (SELECT jsonb_agg(jsonb_build_object(
                          'timestamp',market_discovery_timestamp(o.timestamp),
                          'complete',o.complete,'volume',o.volume,
                          'bid_present',o.bid_present,'ask_present',o.ask_present)
                        ORDER BY o.timestamp)
                   FROM market_historicaltimestampobservation o
                  WHERE o.inventory_id=inventory_row.id))
             OR inventory_row.semantic_inventory_sha256<>market_sha256(
                jsonb_build_object(
                  'logical_discovery_key',canary.logical_key,
                  'canonical_request_sha256',canary.canonical_request_sha256,
                  'observation_count',inventory_row.observation_count,
                  'timestamp_set_sha256',inventory_row.timestamp_set_sha256,
                  'structural_observation_sha256',
                  inventory_row.structural_observation_sha256))
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
          IF attempt_chunk_id=canary.id
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt
                       WHERE chunk_id=attempt_chunk_id)
             OR new_attempt_number<>1
             OR new_idempotency_key<>'historical-discovery-attempt:'
                ||chunk.logical_key||':1'
          THEN RAISE EXCEPTION 'replacement canary activation rejects this attempt'; END IF;
        END """


def _governance():
    return import_module("market.migrations.0014_historical_discovery_supersession")


def _execute(schema_editor, statement):
    # psycopg parses % as a placeholder even with no params; escape literal
    # percent signs so restored verbatim bodies keep single % once stored.
    schema_editor.execute(statement.replace("%", "%%"))


def preflight_full_discovery_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    governance = _governance()
    problems = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('market_historicaldiscoverysupersession')")
        if cursor.fetchone()[0] is None:
            problems.append("supersession table from migration 0014 is missing")
        cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0016_FUNCTIONS)])
        found_functions = {}
        for name, identity_arguments, fingerprint in cursor.fetchall():
            found_functions.setdefault(name, []).append((identity_arguments, fingerprint))
        for name, expected in sorted(REQUIRED_0016_FUNCTIONS.items()):
            candidates = found_functions.get(name, [])
            if not candidates:
                problems.append(f"required 0016 function {name} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0016 function {name} has ambiguous overloads")
            elif candidates[0] != tuple(expected):
                problems.append(f"required 0016 function {name} does not match its 0016 definition")
        cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
        found_triggers = {}
        for table, name, fingerprint in cursor.fetchall():
            found_triggers.setdefault((table, name), []).append(fingerprint)
        for (table, name), expected in sorted(REQUIRED_0016_TRIGGERS.items()):
            candidates = found_triggers.get((table, name), [])
            if not candidates:
                problems.append(f"required 0016 trigger {name} on {table} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0016 trigger {name} on {table} is ambiguous")
            elif candidates[0] != expected:
                problems.append(
                    f"required 0016 trigger {name} on {table} does not match its 0016 definition"
                )
    if problems:
        raise RuntimeError(
            "migration 0017 preflight rejected the current catalog: " + "; ".join(problems)
        )


def install_full_discovery_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_replacement_canary_attempt("
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, "
        "new_idempotency_key text, new_ingestion_run_id bigint) "
        "RETURNS void AS $governed$" + GATE4_ACTIVATION_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )


def remove_full_discovery_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FROM market_historicaldiscoveryattempt a
               JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
               JOIN market_historicaldiscoverysupersession s
                 ON s.replacement_plan_id=c.plan_id
               WHERE c.logical_key <>
                 '63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d'"""
        )
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("full discovery attempts prohibit gate4 activation reversal")
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_replacement_canary_attempt("
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, "
        "new_idempotency_key text, new_ingestion_run_id bigint) "
        "RETURNS void AS $governed$" + CANARY_ACTIVATION_0016_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("market", "0016_provider_observed_h1_alignment_retry"),
    ]

    operations = [
        migrations.RunPython(preflight_full_discovery_activation, migrations.RunPython.noop),
        migrations.RunPython(install_full_discovery_activation, remove_full_discovery_activation),
    ]
