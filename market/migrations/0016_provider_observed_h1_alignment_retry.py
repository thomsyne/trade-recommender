from importlib import import_module

from django.db import migrations

# Full portable fingerprints of the exact 0015-state governance this
# migration depends on and modifies, captured with the 0014 fingerprint
# queries from a catalog migrated exactly through 0015.
REQUIRED_0015_FUNCTIONS = {
    "market_discovery_plan_xact_lock": ("plan_key bigint", "049915d1c7640a273f7c1946d90c272a"),
    "market_discovery_supersession_reject_mutation": ("", "ffdd7694b355279f9caf69aa15c00db9"),
    "market_discovery_supersession_reject_truncate": ("", "e5a8bd59d73d9862ca49fc22828920c1"),
    "market_reject_superseded_discovery_write": ("", "26c4702c5c14f0f00816c67594a81584"),
    "market_validate_discovery_audit_insert": ("", "5639f8ad20d97c0623649dc2fd7d2f51"),
    "market_validate_discovery_observation": ("", "6a15143e3819769cce91d0bfcc2e8842"),
    "market_validate_discovery_supersession": ("", "915337e93db3e0a76a21f31c35ecab6c"),
    "market_validate_replacement_canary_attempt": (
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, new_ingestion_run_id bigint",
        "de9d4072c1f7a01cd7592f1eae8ef997",
    ),
}
REQUIRED_0015_TRIGGERS = {
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
}
DIAGNOSTICS_FUNCTION = "market_discovery_structural_diagnostics_valid"
# Verbatim pg_proc.prosrc bodies restored byte-identically by the empty
# reversal: the 0013 audit-insert validator and the 0015 canary activation.
AUDIT_INSERT_0013_PROSRC = r"""
        DECLARE lineage record; evidence record; existing_count integer; payload_key_count integer;
                expected_provider jsonb; expected_success_diagnostics jsonb; diagnostics jsonb;
                expected_event_body jsonb; expected_event jsonb;
                expected_event_type text; expected_error_code text; expected_stage text;
                expected_diagnostics jsonb;
        BEGIN
          IF NEW.subject_type<>'HistoricalDiscoveryAttempt'
             AND NEW.event_type NOT LIKE 'market.historical_discovery_%'
          THEN RETURN NEW; END IF;
          IF NEW.subject_type<>'HistoricalDiscoveryAttempt'
             OR NEW.event_type NOT IN ('market.historical_discovery_succeeded',
                                       'market.historical_discovery_failed')
             OR NEW.subject_id!~'^[1-9][0-9]*$'
          THEN RAISE EXCEPTION 'invalid discovery terminal audit identity'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended(
            'historical-discovery-audit:'||NEW.subject_id,0));
          SELECT a.attempt_number,a.idempotency_key,c.logical_key,c.granularity,
                 c.requested_from,c.requested_to,c.canonical_request_sha256,i.code,
                 r.status,r.failure_reason,r.fetched_count,inv.semantic_inventory_sha256,
                 inv.observation_count,r.finished_at
            INTO STRICT lineage FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_instrument i ON i.id=c.instrument_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            LEFT JOIN market_historicaltimestampinventory inv ON inv.accepted_attempt_id=a.id
            WHERE a.id=NEW.subject_id::bigint;
          SELECT * INTO STRICT evidence FROM market_historicaldiscoveryproviderevidence
            WHERE attempt_id=NEW.subject_id::bigint;
          SELECT count(*) INTO existing_count FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=NEW.subject_id
              AND audit.event_type IN ('market.historical_discovery_succeeded',
                                       'market.historical_discovery_failed');
          SELECT count(*) INTO payload_key_count FROM jsonb_object_keys(NEW.payload);
          expected_event_type := CASE WHEN lineage.status='succeeded'
            THEN 'market.historical_discovery_succeeded'
            ELSE 'market.historical_discovery_failed' END;
          expected_error_code := nullif(lineage.failure_reason,'');
          expected_provider := jsonb_build_object(
            'canonical_request_sha256',evidence.canonical_request_sha256,
            'endpoint_identity',evidence.endpoint_identity,'environment',evidence.environment,
            'http_method',evidence.http_method,'http_status',evidence.http_status,
            'provider_request_id',evidence.provider_request_id,
            'unavailable_fields',evidence.unavailable_fields);
          diagnostics := NEW.payload->'diagnostics';
          expected_success_diagnostics := jsonb_build_object(
            'observation_count',lineage.observation_count,
            'semantic_inventory_sha256',lineage.semantic_inventory_sha256);
          expected_stage := CASE
            WHEN lineage.status='succeeded' THEN 'complete'
            WHEN expected_error_code='DISCOVERY_PERSISTENCE_FAILED' THEN 'persistence'
            WHEN expected_error_code='DISCOVERY_STALE_ATTEMPT' THEN 'stale_resolution'
            WHEN expected_error_code IN ('DISCOVERY_PROVIDER_AUTH_ERROR',
                 'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                 'DISCOVERY_UNKNOWN_FAILURE') THEN 'provider_request'
            WHEN expected_error_code='DISCOVERY_PROVIDER_EVIDENCE_MISSING'
              THEN 'provider_evidence'
            WHEN expected_error_code IN ('DISCOVERY_PROVIDER_LIMIT_SUSPECTED',
                 'DISCOVERY_STRUCTURE_INVALID') THEN 'response_validation'
            ELSE NULL END;
          expected_diagnostics := CASE
            WHEN lineage.status='succeeded' THEN expected_success_diagnostics
            WHEN expected_error_code='DISCOVERY_PERSISTENCE_FAILED' THEN
              jsonb_build_object('component',diagnostics->>'component')
            WHEN expected_error_code='DISCOVERY_STALE_ATTEMPT' THEN jsonb_build_object(
              'reason',diagnostics->>'reason','stale_threshold_seconds',
              (diagnostics->>'stale_threshold_seconds')::integer)
            WHEN expected_error_code IN ('DISCOVERY_PROVIDER_AUTH_ERROR',
                 'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                 'DISCOVERY_UNKNOWN_FAILURE') THEN '{}'::jsonb
            WHEN expected_error_code='DISCOVERY_PROVIDER_EVIDENCE_MISSING' THEN
              jsonb_build_object('unavailable_fields',evidence.unavailable_fields)
            WHEN expected_error_code='DISCOVERY_PROVIDER_LIMIT_SUSPECTED' THEN
              jsonb_build_object('observation_count',lineage.fetched_count)
            WHEN expected_error_code='DISCOVERY_STRUCTURE_INVALID' THEN diagnostics
            ELSE NULL END;
          expected_event_body := jsonb_build_object(
            'schema_version',1,
            'error_code',expected_error_code,
            'stage',expected_stage,
            'logical_discovery_key',lineage.logical_key,
            'attempt_number',lineage.attempt_number,
            'idempotency_key',lineage.idempotency_key,
            'instrument',lineage.code,
            'granularity',lineage.granularity,
            'requested_from',market_discovery_timestamp(lineage.requested_from),
            'requested_to',market_discovery_timestamp(lineage.requested_to),
            'canonical_request_sha256',lineage.canonical_request_sha256,
            'provider_evidence',expected_provider,
            'diagnostics',expected_diagnostics,
            'occurred_at',market_discovery_operational_timestamp(lineage.finished_at));
          expected_event := expected_event_body || jsonb_build_object(
            'event_sha256',market_sha256(expected_event_body));
          IF existing_count<>0 OR NEW.event_type IS DISTINCT FROM expected_event_type
             OR NEW.actor IS DISTINCT FROM 'market.historical_discovery.run_discovery_chunk'
             OR payload_key_count<>15 OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
             OR NEW.payload IS DISTINCT FROM expected_event
             OR NEW.payload->>'schema_version' IS DISTINCT FROM '1'
             OR NEW.payload->>'logical_discovery_key' IS DISTINCT FROM lineage.logical_key
             OR (NEW.payload->>'attempt_number')::integer IS DISTINCT FROM lineage.attempt_number
             OR NEW.payload->>'idempotency_key' IS DISTINCT FROM lineage.idempotency_key
             OR NEW.payload->>'instrument' IS DISTINCT FROM lineage.code
             OR NEW.payload->>'granularity' IS DISTINCT FROM lineage.granularity
             OR NEW.payload->>'requested_from' IS DISTINCT FROM
                market_discovery_timestamp(lineage.requested_from)
             OR NEW.payload->>'requested_to' IS DISTINCT FROM
                market_discovery_timestamp(lineage.requested_to)
             OR NEW.payload->>'canonical_request_sha256' IS DISTINCT FROM
                lineage.canonical_request_sha256
             OR NEW.payload->'provider_evidence' IS DISTINCT FROM expected_provider
             OR NEW.payload->>'occurred_at' IS DISTINCT FROM
                market_discovery_operational_timestamp((SELECT finished_at FROM market_ingestionrun
                  WHERE id=(SELECT ingestion_run_id FROM market_historicaldiscoveryattempt
                            WHERE id=NEW.subject_id::bigint)))
             OR NEW.payload->>'event_sha256' IS DISTINCT FROM
                market_sha256(NEW.payload-'event_sha256')
             OR jsonb_typeof(diagnostics) IS DISTINCT FROM 'object'
             OR octet_length(diagnostics::text)>4096
             OR diagnostics::text~*'"(authorization|token|password|secret|raw_url|account_id|body|bid_open|bid_high|bid_low|bid_close|ask_open|ask_high|ask_low|ask_close)"[[:space:]]*:'
             OR (lineage.status='succeeded' AND (
                  NEW.payload->'error_code' IS DISTINCT FROM 'null'::jsonb
                  OR NEW.payload->>'stage' IS DISTINCT FROM 'complete'
                  OR diagnostics IS DISTINCT FROM expected_success_diagnostics))
             OR (lineage.status='failed' AND (
                  NEW.payload->>'error_code' IS DISTINCT FROM expected_error_code
                  OR (expected_error_code='DISCOVERY_PERSISTENCE_FAILED' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'persistence'
                      OR diagnostics->>'component' IS NULL
                      OR diagnostics->>'component' NOT IN
                         ('inventory','observations','run','provider_evidence','audit_event',
                          'database_constraints')
                      OR diagnostics IS DISTINCT FROM
                         jsonb_build_object('component',diagnostics->>'component')))
                  OR (expected_error_code='DISCOVERY_STALE_ATTEMPT' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'stale_resolution'
                      OR diagnostics->>'reason' IS NULL
                      OR diagnostics->>'reason'!~'^[A-Z][A-Z0-9_]{2,79}$'
                      OR diagnostics->>'stale_threshold_seconds' IS NULL
                      OR (diagnostics->>'stale_threshold_seconds')::integer<=0
                      OR diagnostics IS DISTINCT FROM jsonb_build_object(
                         'reason',diagnostics->>'reason','stale_threshold_seconds',
                         (diagnostics->>'stale_threshold_seconds')::integer)))
                  OR (expected_error_code IN ('DISCOVERY_PROVIDER_AUTH_ERROR',
                      'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                      'DISCOVERY_UNKNOWN_FAILURE') AND
                      (NEW.payload->>'stage' IS DISTINCT FROM 'provider_request'
                       OR diagnostics IS DISTINCT FROM '{}'::jsonb))
                  OR (expected_error_code='DISCOVERY_PROVIDER_EVIDENCE_MISSING' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'provider_evidence'
                      OR diagnostics IS DISTINCT FROM jsonb_build_object(
                         'unavailable_fields',evidence.unavailable_fields)))
                  OR (expected_error_code='DISCOVERY_PROVIDER_LIMIT_SUSPECTED' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'response_validation'
                      OR diagnostics IS DISTINCT FROM
                         jsonb_build_object('observation_count',lineage.fetched_count)))
                  OR (expected_error_code='DISCOVERY_STRUCTURE_INVALID' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'response_validation'
                      OR (SELECT count(*) FROM jsonb_object_keys(diagnostics))<>3
                      OR jsonb_typeof(diagnostics->'issue_counts') IS DISTINCT FROM 'object'
                      OR jsonb_typeof(diagnostics->'issue_samples') IS DISTINCT FROM 'array'
                      OR jsonb_typeof(diagnostics->'diagnostic_truncated') IS DISTINCT FROM
                         'boolean'
                      OR jsonb_array_length(diagnostics->'issue_samples')>32
                      OR EXISTS(SELECT 1 FROM jsonb_each(diagnostics->'issue_counts') issue
                        WHERE issue.key NOT IN ('malformed_observation','timestamp_out_of_range',
                          'timestamp_misaligned','completeness_missing','incomplete','invalid_volume',
                          'bid_missing','ask_missing','unordered_timestamps',
                          'duplicate_timestamps','empty_response')
                          OR jsonb_typeof(issue.value)<>'number'
                          OR (issue.value#>>'{}')::integer<1)
                      OR EXISTS(SELECT 1 FROM jsonb_array_elements(
                          diagnostics->'issue_samples') sample
                        WHERE jsonb_typeof(sample)<>'object'
                          OR (SELECT count(*) FROM jsonb_object_keys(sample))<>2
                          OR sample->>'code' NOT IN ('malformed_observation',
                            'timestamp_out_of_range','timestamp_misaligned','completeness_missing',
                            'incomplete','invalid_volume','bid_missing','ask_missing',
                            'unordered_timestamps','duplicate_timestamps','empty_response')
                          OR (sample->'index'<>'null'::jsonb AND
                              (jsonb_typeof(sample->'index')<>'number'
                               OR (sample->>'index')::integer<0)))))
                  OR expected_error_code NOT IN ('DISCOVERY_PERSISTENCE_FAILED',
                     'DISCOVERY_STALE_ATTEMPT','DISCOVERY_PROVIDER_AUTH_ERROR',
                     'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                     'DISCOVERY_UNKNOWN_FAILURE','DISCOVERY_PROVIDER_EVIDENCE_MISSING',
                     'DISCOVERY_PROVIDER_LIMIT_SUSPECTED','DISCOVERY_STRUCTURE_INVALID')))
          THEN RAISE EXCEPTION 'discovery terminal audit event does not reconstruct'; END IF;
          RETURN NEW;
        END """
CANARY_ACTIVATION_0015_PROSRC = r"""
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
        END """
OBSERVATION_0013_PROSRC = r"""
        DECLARE lineage record; local_time timestamp;
        BEGIN
          SELECT c.requested_from,c.requested_to,c.granularity,p.sealed_at,r.status
            INTO STRICT lineage
            FROM market_historicaltimestampinventory inv
            JOIN market_historicaldiscoverychunk c ON c.id=inv.chunk_id
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_historicaldiscoveryattempt a ON a.id=inv.accepted_attempt_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE inv.id=NEW.inventory_id;
          local_time := NEW.timestamp AT TIME ZONE 'America/New_York';
          IF lineage.sealed_at IS NOT NULL OR lineage.status<>'running'
             OR NEW.timestamp<lineage.requested_from
             OR NEW.timestamp>=lineage.requested_to
             OR date_trunc('second',NEW.timestamp)<>NEW.timestamp
             OR NOT NEW.complete OR NOT NEW.bid_present OR NOT NEW.ask_present
             OR (lineage.granularity='D' AND local_time::time<>time '17:00')
             OR (lineage.granularity='W' AND
                 (extract(isodow FROM local_time)<>5 OR local_time::time<>time '17:00'))
             OR (lineage.granularity='H1' AND (
                 date_trunc('hour',local_time)<>local_time OR
                 extract(isodow FROM local_time)=6 OR
                 (extract(isodow FROM local_time)=5 AND local_time::time>=time '17:00') OR
                 (extract(isodow FROM local_time)=7 AND local_time::time<time '17:00')))
          THEN RAISE EXCEPTION 'invalid structural discovery observation'; END IF;
          RETURN NEW;
        END """
REVISED_OBSERVATION_PROSRC = r"""
        DECLARE lineage record; local_time timestamp;
        BEGIN
          SELECT c.requested_from,c.requested_to,c.granularity,p.sealed_at,p.version,
                 r.status
            INTO STRICT lineage
            FROM market_historicaltimestampinventory inv
            JOIN market_historicaldiscoverychunk c ON c.id=inv.chunk_id
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_historicaldiscoveryattempt a ON a.id=inv.accepted_attempt_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE inv.id=NEW.inventory_id;
          local_time := NEW.timestamp AT TIME ZONE 'America/New_York';
          IF lineage.sealed_at IS NOT NULL OR lineage.status<>'running'
             OR NEW.timestamp<lineage.requested_from
             OR NEW.timestamp>=lineage.requested_to
             OR date_trunc('second',NEW.timestamp)<>NEW.timestamp
             OR NOT NEW.complete OR NOT NEW.bid_present OR NOT NEW.ask_present
             OR (lineage.granularity='D' AND local_time::time<>time '17:00')
             OR (lineage.granularity='W' AND
                 (extract(isodow FROM local_time)<>5 OR local_time::time<>time '17:00'))
             OR (lineage.granularity='H1'
                 AND lineage.version='phase-2b1r-discovery-v1' AND (
                 date_trunc('hour',local_time)<>local_time OR
                 extract(isodow FROM local_time)=6 OR
                 (extract(isodow FROM local_time)=5 AND local_time::time>=time '17:00') OR
                 (extract(isodow FROM local_time)=7 AND local_time::time<time '17:00')))
             OR (lineage.granularity='H1'
                 AND lineage.version<>'phase-2b1r-discovery-v1'
                 AND date_trunc('hour',NEW.timestamp AT TIME ZONE 'UTC')
                     <>NEW.timestamp AT TIME ZONE 'UTC')
          THEN RAISE EXCEPTION 'invalid structural discovery observation'; END IF;
          RETURN NEW;
        END """


REVISED_AUDIT_PROSRC = r"""
        DECLARE lineage record; evidence record; existing_count integer; payload_key_count integer;
                expected_provider jsonb; expected_success_diagnostics jsonb; diagnostics jsonb;
                expected_event_body jsonb; expected_event jsonb;
                expected_event_type text; expected_error_code text; expected_stage text;
                expected_diagnostics jsonb;
        BEGIN
          IF NEW.subject_type<>'HistoricalDiscoveryAttempt'
             AND NEW.event_type NOT LIKE 'market.historical_discovery_%'
          THEN RETURN NEW; END IF;
          IF NEW.subject_type<>'HistoricalDiscoveryAttempt'
             OR NEW.event_type NOT IN ('market.historical_discovery_succeeded',
                                       'market.historical_discovery_failed')
             OR NEW.subject_id!~'^[1-9][0-9]*$'
          THEN RAISE EXCEPTION 'invalid discovery terminal audit identity'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended(
            'historical-discovery-audit:'||NEW.subject_id,0));
          SELECT a.attempt_number,a.idempotency_key,c.logical_key,c.granularity,
                 c.requested_from,c.requested_to,c.canonical_request_sha256,i.code,
                 r.status,r.failure_reason,r.fetched_count,inv.semantic_inventory_sha256,
                 inv.observation_count,r.finished_at
            INTO STRICT lineage FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_instrument i ON i.id=c.instrument_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            LEFT JOIN market_historicaltimestampinventory inv ON inv.accepted_attempt_id=a.id
            WHERE a.id=NEW.subject_id::bigint;
          SELECT * INTO STRICT evidence FROM market_historicaldiscoveryproviderevidence
            WHERE attempt_id=NEW.subject_id::bigint;
          SELECT count(*) INTO existing_count FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=NEW.subject_id
              AND audit.event_type IN ('market.historical_discovery_succeeded',
                                       'market.historical_discovery_failed');
          SELECT count(*) INTO payload_key_count FROM jsonb_object_keys(NEW.payload);
          expected_event_type := CASE WHEN lineage.status='succeeded'
            THEN 'market.historical_discovery_succeeded'
            ELSE 'market.historical_discovery_failed' END;
          expected_error_code := nullif(lineage.failure_reason,'');
          expected_provider := jsonb_build_object(
            'canonical_request_sha256',evidence.canonical_request_sha256,
            'endpoint_identity',evidence.endpoint_identity,'environment',evidence.environment,
            'http_method',evidence.http_method,'http_status',evidence.http_status,
            'provider_request_id',evidence.provider_request_id,
            'unavailable_fields',evidence.unavailable_fields);
          diagnostics := NEW.payload->'diagnostics';
          expected_success_diagnostics := jsonb_build_object(
            'observation_count',lineage.observation_count,
            'semantic_inventory_sha256',lineage.semantic_inventory_sha256);
          expected_stage := CASE
            WHEN lineage.status='succeeded' THEN 'complete'
            WHEN expected_error_code='DISCOVERY_PERSISTENCE_FAILED' THEN 'persistence'
            WHEN expected_error_code='DISCOVERY_STALE_ATTEMPT' THEN 'stale_resolution'
            WHEN expected_error_code IN ('DISCOVERY_PROVIDER_AUTH_ERROR',
                 'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                 'DISCOVERY_UNKNOWN_FAILURE') THEN 'provider_request'
            WHEN expected_error_code='DISCOVERY_PROVIDER_EVIDENCE_MISSING'
              THEN 'provider_evidence'
            WHEN expected_error_code IN ('DISCOVERY_PROVIDER_LIMIT_SUSPECTED',
                 'DISCOVERY_STRUCTURE_INVALID') THEN 'response_validation'
            ELSE NULL END;
          expected_diagnostics := CASE
            WHEN lineage.status='succeeded' THEN expected_success_diagnostics
            WHEN expected_error_code='DISCOVERY_PERSISTENCE_FAILED' THEN
              jsonb_build_object('component',diagnostics->>'component')
            WHEN expected_error_code='DISCOVERY_STALE_ATTEMPT' THEN jsonb_build_object(
              'reason',diagnostics->>'reason','stale_threshold_seconds',
              (diagnostics->>'stale_threshold_seconds')::integer)
            WHEN expected_error_code IN ('DISCOVERY_PROVIDER_AUTH_ERROR',
                 'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                 'DISCOVERY_UNKNOWN_FAILURE') THEN '{}'::jsonb
            WHEN expected_error_code='DISCOVERY_PROVIDER_EVIDENCE_MISSING' THEN
              jsonb_build_object('unavailable_fields',evidence.unavailable_fields)
            WHEN expected_error_code='DISCOVERY_PROVIDER_LIMIT_SUSPECTED' THEN
              jsonb_build_object('observation_count',lineage.fetched_count)
            WHEN expected_error_code='DISCOVERY_STRUCTURE_INVALID' THEN
              CASE WHEN market_discovery_structural_diagnostics_valid(
                     diagnostics, lineage.fetched_count)
                   THEN diagnostics ELSE NULL END
            ELSE NULL END;
          expected_event_body := jsonb_build_object(
            'schema_version',1,
            'error_code',expected_error_code,
            'stage',expected_stage,
            'logical_discovery_key',lineage.logical_key,
            'attempt_number',lineage.attempt_number,
            'idempotency_key',lineage.idempotency_key,
            'instrument',lineage.code,
            'granularity',lineage.granularity,
            'requested_from',market_discovery_timestamp(lineage.requested_from),
            'requested_to',market_discovery_timestamp(lineage.requested_to),
            'canonical_request_sha256',lineage.canonical_request_sha256,
            'provider_evidence',expected_provider,
            'diagnostics',expected_diagnostics,
            'occurred_at',market_discovery_operational_timestamp(lineage.finished_at));
          expected_event := expected_event_body || jsonb_build_object(
            'event_sha256',market_sha256(expected_event_body));
          IF existing_count<>0 OR NEW.event_type IS DISTINCT FROM expected_event_type
             OR NEW.actor IS DISTINCT FROM 'market.historical_discovery.run_discovery_chunk'
             OR payload_key_count<>15 OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
             OR NEW.payload IS DISTINCT FROM expected_event
             OR NEW.payload->>'schema_version' IS DISTINCT FROM '1'
             OR NEW.payload->>'logical_discovery_key' IS DISTINCT FROM lineage.logical_key
             OR (NEW.payload->>'attempt_number')::integer IS DISTINCT FROM lineage.attempt_number
             OR NEW.payload->>'idempotency_key' IS DISTINCT FROM lineage.idempotency_key
             OR NEW.payload->>'instrument' IS DISTINCT FROM lineage.code
             OR NEW.payload->>'granularity' IS DISTINCT FROM lineage.granularity
             OR NEW.payload->>'requested_from' IS DISTINCT FROM
                market_discovery_timestamp(lineage.requested_from)
             OR NEW.payload->>'requested_to' IS DISTINCT FROM
                market_discovery_timestamp(lineage.requested_to)
             OR NEW.payload->>'canonical_request_sha256' IS DISTINCT FROM
                lineage.canonical_request_sha256
             OR NEW.payload->'provider_evidence' IS DISTINCT FROM expected_provider
             OR NEW.payload->>'occurred_at' IS DISTINCT FROM
                market_discovery_operational_timestamp((SELECT finished_at FROM market_ingestionrun
                  WHERE id=(SELECT ingestion_run_id FROM market_historicaldiscoveryattempt
                            WHERE id=NEW.subject_id::bigint)))
             OR NEW.payload->>'event_sha256' IS DISTINCT FROM
                market_sha256(NEW.payload-'event_sha256')
             OR jsonb_typeof(diagnostics) IS DISTINCT FROM 'object'
             OR octet_length(diagnostics::text)>
                (CASE WHEN expected_error_code='DISCOVERY_STRUCTURE_INVALID'
                      THEN 131072 ELSE 4096 END)
             OR diagnostics::text~*'"(authorization|token|password|secret|raw_url|account_id|body|bid_open|bid_high|bid_low|bid_close|ask_open|ask_high|ask_low|ask_close)"[[:space:]]*:'
             OR (lineage.status='succeeded' AND (
                  NEW.payload->'error_code' IS DISTINCT FROM 'null'::jsonb
                  OR NEW.payload->>'stage' IS DISTINCT FROM 'complete'
                  OR diagnostics IS DISTINCT FROM expected_success_diagnostics))
             OR (lineage.status='failed' AND (
                  NEW.payload->>'error_code' IS DISTINCT FROM expected_error_code
                  OR (expected_error_code='DISCOVERY_PERSISTENCE_FAILED' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'persistence'
                      OR diagnostics->>'component' IS NULL
                      OR diagnostics->>'component' NOT IN
                         ('inventory','observations','run','provider_evidence','audit_event',
                          'database_constraints')
                      OR diagnostics IS DISTINCT FROM
                         jsonb_build_object('component',diagnostics->>'component')))
                  OR (expected_error_code='DISCOVERY_STALE_ATTEMPT' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'stale_resolution'
                      OR diagnostics->>'reason' IS NULL
                      OR diagnostics->>'reason'!~'^[A-Z][A-Z0-9_]{2,79}$'
                      OR diagnostics->>'stale_threshold_seconds' IS NULL
                      OR (diagnostics->>'stale_threshold_seconds')::integer<=0
                      OR diagnostics IS DISTINCT FROM jsonb_build_object(
                         'reason',diagnostics->>'reason','stale_threshold_seconds',
                         (diagnostics->>'stale_threshold_seconds')::integer)))
                  OR (expected_error_code IN ('DISCOVERY_PROVIDER_AUTH_ERROR',
                      'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                      'DISCOVERY_UNKNOWN_FAILURE') AND
                      (NEW.payload->>'stage' IS DISTINCT FROM 'provider_request'
                       OR diagnostics IS DISTINCT FROM '{}'::jsonb))
                  OR (expected_error_code='DISCOVERY_PROVIDER_EVIDENCE_MISSING' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'provider_evidence'
                      OR diagnostics IS DISTINCT FROM jsonb_build_object(
                         'unavailable_fields',evidence.unavailable_fields)))
                  OR (expected_error_code='DISCOVERY_PROVIDER_LIMIT_SUSPECTED' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'response_validation'
                      OR diagnostics IS DISTINCT FROM
                         jsonb_build_object('observation_count',lineage.fetched_count)))
                  OR (expected_error_code='DISCOVERY_STRUCTURE_INVALID' AND (
                      NEW.payload->>'stage' IS DISTINCT FROM 'response_validation'
                      OR NOT market_discovery_structural_diagnostics_valid(
                           diagnostics, lineage.fetched_count)))
                  OR expected_error_code NOT IN ('DISCOVERY_PERSISTENCE_FAILED',
                     'DISCOVERY_STALE_ATTEMPT','DISCOVERY_PROVIDER_AUTH_ERROR',
                     'DISCOVERY_PROVIDER_HTTP_ERROR','DISCOVERY_PROVIDER_RESPONSE_MALFORMED',
                     'DISCOVERY_UNKNOWN_FAILURE','DISCOVERY_PROVIDER_EVIDENCE_MISSING',
                     'DISCOVERY_PROVIDER_LIMIT_SUSPECTED','DISCOVERY_STRUCTURE_INVALID')))
          THEN RAISE EXCEPTION 'discovery terminal audit event does not reconstruct'; END IF;
          RETURN NEW;
        END """
RETRY_ACTIVATION_PROSRC = r"""
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


def _governance():
    return import_module("market.migrations.0014_historical_discovery_supersession")


def _execute(schema_editor, statement):
    # psycopg parses % as a placeholder even with no params; escape literal
    # percent signs so restored verbatim bodies keep single % once stored.
    schema_editor.execute(statement.replace("%", "%%"))


def preflight_h1_alignment_retry(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    governance = _governance()
    problems = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('market_historicaldiscoverysupersession')")
        if cursor.fetchone()[0] is None:
            problems.append("supersession table from migration 0014 is missing")
        cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0015_FUNCTIONS)])
        found_functions = {}
        for name, identity_arguments, fingerprint in cursor.fetchall():
            found_functions.setdefault(name, []).append((identity_arguments, fingerprint))
        for name, expected in sorted(REQUIRED_0015_FUNCTIONS.items()):
            candidates = found_functions.get(name, [])
            if not candidates:
                problems.append(f"required 0015 function {name} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0015 function {name} has ambiguous overloads")
            elif candidates[0] != tuple(expected):
                problems.append(f"required 0015 function {name} does not match its 0015 definition")
        cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
        found_triggers = {}
        for table, name, fingerprint in cursor.fetchall():
            found_triggers.setdefault((table, name), []).append(fingerprint)
        for (table, name), expected in sorted(REQUIRED_0015_TRIGGERS.items()):
            candidates = found_triggers.get((table, name), [])
            if not candidates:
                problems.append(f"required 0015 trigger {name} on {table} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0015 trigger {name} on {table} is ambiguous")
            elif candidates[0] != expected:
                problems.append(
                    f"required 0015 trigger {name} on {table} does not match its 0015 definition"
                )
        cursor.execute(
            """SELECT count(*) FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = current_schema() AND p.proname = %s""",
            [DIAGNOSTICS_FUNCTION],
        )
        if cursor.fetchone()[0] != 0:
            problems.append(f"unexpected pre-existing function {DIAGNOSTICS_FUNCTION}")
    if problems:
        raise RuntimeError(
            "migration 0016 preflight rejected the current catalog: " + "; ".join(problems)
        )


def install_h1_alignment_retry(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _execute(
        schema_editor,
        r"""
        CREATE FUNCTION market_discovery_structural_diagnostics_valid(
          diagnostics jsonb, fetched integer) RETURNS boolean AS $$
        DECLARE total_issues bigint; sample jsonb; sample_count integer;
                sample_utc timestamptz; weekday_sum bigint; hour_sum bigint;
                offset_sum bigint;
        BEGIN
          IF jsonb_typeof(diagnostics)<>'object'
             OR (SELECT array_agg(key ORDER BY key)
                   FROM jsonb_object_keys(diagnostics) key)
                <> ARRAY['diagnostic_truncated','first_observed_timestamp',
                         'invalid_timestamp_set_sha256','issue_counts',
                         'issue_counts_by_new_york_hour',
                         'issue_counts_by_new_york_weekday',
                         'issue_counts_by_utc_offset','issue_samples',
                         'last_observed_timestamp','observation_count',
                         'observed_timestamp_set_sha256']
          THEN RETURN false; END IF;
          IF jsonb_typeof(diagnostics->'observation_count')<>'number'
             OR (diagnostics->>'observation_count')::bigint<>fetched
             OR jsonb_typeof(diagnostics->'issue_counts')<>'object'
             OR jsonb_typeof(diagnostics->'issue_samples')<>'array'
             OR jsonb_typeof(diagnostics->'diagnostic_truncated')<>'boolean'
             OR jsonb_typeof(diagnostics->'issue_counts_by_new_york_weekday')<>'object'
             OR jsonb_typeof(diagnostics->'issue_counts_by_new_york_hour')<>'object'
             OR jsonb_typeof(diagnostics->'issue_counts_by_utc_offset')<>'object'
             OR diagnostics->>'observed_timestamp_set_sha256' !~ '^[0-9a-f]{64}$'
             OR diagnostics->>'invalid_timestamp_set_sha256' !~ '^[0-9a-f]{64}$'
             OR NOT (diagnostics->'first_observed_timestamp'='null'::jsonb
                     OR diagnostics->>'first_observed_timestamp'
                        ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
             OR NOT (diagnostics->'last_observed_timestamp'='null'::jsonb
                     OR diagnostics->>'last_observed_timestamp'
                        ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
          THEN RETURN false; END IF;
          IF EXISTS(SELECT 1 FROM jsonb_each(diagnostics->'issue_counts') pair
                    WHERE jsonb_typeof(pair.value)<>'number'
                       OR (pair.value)::text !~ '^[1-9][0-9]{0,9}$'
                       OR pair.key NOT IN ('malformed_observation',
                          'timestamp_out_of_range','timestamp_misaligned',
                          'completeness_missing','incomplete','invalid_volume',
                          'bid_missing','ask_missing','unordered_timestamps',
                          'duplicate_timestamps','empty_response'))
          THEN RETURN false; END IF;
          IF EXISTS(SELECT 1 FROM jsonb_each(
                      diagnostics->'issue_counts_by_new_york_weekday') pair
                    WHERE pair.key !~ '^[0-6]$'
                       OR jsonb_typeof(pair.value)<>'number'
                       OR (pair.value)::text !~ '^[1-9][0-9]{0,9}$')
             OR EXISTS(SELECT 1 FROM jsonb_each(
                      diagnostics->'issue_counts_by_new_york_hour') pair
                    WHERE pair.key !~ '^([0-9]|1[0-9]|2[0-3])$'
                       OR jsonb_typeof(pair.value)<>'number'
                       OR (pair.value)::text !~ '^[1-9][0-9]{0,9}$')
             OR EXISTS(SELECT 1 FROM jsonb_each(
                      diagnostics->'issue_counts_by_utc_offset') pair
                    WHERE pair.key !~ '^-?[0-9]{1,6}$'
                       OR jsonb_typeof(pair.value)<>'number'
                       OR (pair.value)::text !~ '^[1-9][0-9]{0,9}$')
          THEN RETURN false; END IF;
          SELECT coalesce(sum(value::bigint),0) INTO total_issues
            FROM jsonb_each_text(diagnostics->'issue_counts');
          SELECT coalesce(sum(value::bigint),0) INTO weekday_sum
            FROM jsonb_each_text(diagnostics->'issue_counts_by_new_york_weekday');
          SELECT coalesce(sum(value::bigint),0) INTO hour_sum
            FROM jsonb_each_text(diagnostics->'issue_counts_by_new_york_hour');
          SELECT coalesce(sum(value::bigint),0) INTO offset_sum
            FROM jsonb_each_text(diagnostics->'issue_counts_by_utc_offset');
          IF weekday_sum<>hour_sum OR hour_sum<>offset_sum OR weekday_sum>total_issues
          THEN RETURN false; END IF;
          sample_count := jsonb_array_length(diagnostics->'issue_samples');
          IF sample_count<>LEAST(total_issues,256)
             OR (diagnostics->'diagnostic_truncated')::text::boolean
                IS DISTINCT FROM (total_issues>256)
          THEN RETURN false; END IF;
          FOR sample IN SELECT * FROM jsonb_array_elements(diagnostics->'issue_samples')
          LOOP
            IF jsonb_typeof(sample)<>'object'
               OR (SELECT array_agg(key ORDER BY key)
                     FROM jsonb_object_keys(sample) key)
                  <> ARRAY['ask_present','bid_present','code','complete','index',
                           'new_york_weekday','timestamp_new_york','timestamp_utc',
                           'utc_offset_seconds','volume']
               OR jsonb_typeof(sample->'code')<>'string'
               OR sample->>'code' NOT IN ('malformed_observation',
                  'timestamp_out_of_range','timestamp_misaligned',
                  'completeness_missing','incomplete','invalid_volume',
                  'bid_missing','ask_missing','unordered_timestamps',
                  'duplicate_timestamps','empty_response')
               OR NOT diagnostics->'issue_counts' ? (sample->>'code')
               OR jsonb_typeof(sample->'index') NOT IN ('number','null')
               OR (jsonb_typeof(sample->'index')='number' AND
                   ((sample->'index')::text !~ '^(0|[1-9][0-9]{0,9})$'
                    OR (sample->>'index')::bigint>=fetched))
               OR jsonb_typeof(sample->'timestamp_utc') NOT IN ('string','null')
               OR (jsonb_typeof(sample->'timestamp_utc')='string'
                   AND sample->>'timestamp_utc'
                       !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
               OR jsonb_typeof(sample->'timestamp_new_york') NOT IN ('string','null')
               OR (jsonb_typeof(sample->'timestamp_new_york')='string'
                   AND sample->>'timestamp_new_york'
                       !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$')
               OR (jsonb_typeof(sample->'timestamp_utc')
                   <>jsonb_typeof(sample->'timestamp_new_york'))
               OR jsonb_typeof(sample->'new_york_weekday') NOT IN ('number','null')
               OR (jsonb_typeof(sample->'new_york_weekday')='number'
                   AND (sample->'new_york_weekday')::text !~ '^[0-6]$')
               OR jsonb_typeof(sample->'utc_offset_seconds') NOT IN ('number','null')
               OR (jsonb_typeof(sample->'utc_offset_seconds')='number'
                   AND (sample->'utc_offset_seconds')::text !~ '^-?[0-9]{1,6}$')
               OR jsonb_typeof(sample->'complete') NOT IN ('boolean','null')
               OR jsonb_typeof(sample->'volume') NOT IN ('number','null')
               OR (jsonb_typeof(sample->'volume')='number'
                   AND (sample->'volume')::text !~ '^(0|[1-9][0-9]{0,18})$')
               OR jsonb_typeof(sample->'bid_present') NOT IN ('boolean','null')
               OR jsonb_typeof(sample->'ask_present') NOT IN ('boolean','null')
            THEN RETURN false; END IF;
            IF jsonb_typeof(sample->'timestamp_utc')='string' THEN
              sample_utc := (sample->>'timestamp_utc')::timestamptz;
              IF (sample->>'timestamp_new_york')::timestamptz IS DISTINCT FROM sample_utc
                 OR jsonb_typeof(sample->'new_york_weekday')<>'number'
                 OR (sample->>'new_york_weekday')::int
                    <>(extract(isodow FROM (sample_utc
                        AT TIME ZONE 'America/New_York'))::int - 1)
                 OR jsonb_typeof(sample->'utc_offset_seconds')<>'number'
                 OR (sample->>'utc_offset_seconds')::int
                    <>(extract(epoch FROM (
                        (sample_utc AT TIME ZONE 'America/New_York')
                        -(sample_utc AT TIME ZONE 'UTC'))))::int
              THEN RETURN false; END IF;
            END IF;
          END LOOP;
          RETURN true;
        END $$ LANGUAGE plpgsql;
""",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_discovery_audit_insert() "
        "RETURNS trigger AS $governed$" + REVISED_AUDIT_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_discovery_observation() "
        "RETURNS trigger AS $governed$" + REVISED_OBSERVATION_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_replacement_canary_attempt("
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, "
        "new_idempotency_key text, new_ingestion_run_id bigint) "
        "RETURNS void AS $governed$" + RETRY_ACTIVATION_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )


def remove_h1_alignment_retry(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FROM market_historicaldiscoveryattempt a
               JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
               JOIN market_historicaldiscoverysupersession s
                 ON s.replacement_plan_id=c.plan_id
               WHERE a.attempt_number >= 2"""
        )
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("canary retry evidence prohibits h1 alignment migration reversal")
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_replacement_canary_attempt("
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, "
        "new_idempotency_key text, new_ingestion_run_id bigint) "
        "RETURNS void AS $governed$" + CANARY_ACTIVATION_0015_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_discovery_audit_insert() "
        "RETURNS trigger AS $governed$" + AUDIT_INSERT_0013_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_discovery_observation() "
        "RETURNS trigger AS $governed$" + OBSERVATION_0013_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "DROP FUNCTION IF EXISTS market_discovery_structural_diagnostics_valid(jsonb, integer);",
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("market", "0015_provider_observed_canary_activation"),
    ]

    operations = [
        migrations.RunPython(preflight_h1_alignment_retry, migrations.RunPython.noop),
        migrations.RunPython(install_h1_alignment_retry, remove_h1_alignment_retry),
    ]
