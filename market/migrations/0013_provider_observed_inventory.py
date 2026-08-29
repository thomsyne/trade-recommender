import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

DISCOVERY_TABLES = (
    "market_historicaldiscoveryregistration",
    "market_historicaldiscoveryapproval",
    "market_historicaldiscoveryproviderevidence",
    "market_historicaltimestampobservation",
    "market_historicaltimestampinventory",
    "market_historicaldiscoveryattempt",
    "market_historicaldiscoverychunk",
    "market_historicaldiscoveryplan",
)


def preflight_discovery_schema(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM market_ingestionrun "
            "WHERE parameters->>'purpose'='provider_timestamp_inventory_discovery'), "
            "ARRAY(SELECT table_name FROM unnest(%s::text[]) table_name "
            "WHERE to_regclass(table_name) IS NOT NULL)",
            [list(DISCOVERY_TABLES)],
        )
        has_runs, tables = cursor.fetchone()
    if has_runs or tables:
        raise RuntimeError("unexpected provider-observed discovery evidence exists")


def install_discovery_governance(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        r"""
        CREATE FUNCTION market_discovery_timestamp(value timestamptz) RETURNS text AS $$
          SELECT to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS') || 'Z'
        $$ LANGUAGE sql IMMUTABLE STRICT;

        CREATE FUNCTION market_discovery_operational_timestamp(value timestamptz) RETURNS text AS $$
          SELECT to_char(value AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00'
        $$ LANGUAGE sql IMMUTABLE STRICT;

        CREATE FUNCTION market_discovery_reject_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'historical discovery evidence is append-only';
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_discovery_reject_truncate() RETURNS trigger AS $$
        BEGIN
          IF current_database() LIKE 'test\_%%' ESCAPE '\'
             AND EXISTS(
               SELECT 1 FROM pg_locks locks
               WHERE locks.pid=pg_backend_pid() AND locks.granted
                 AND locks.mode='AccessExclusiveLock'
                 AND locks.relation='auth_permission'::regclass
             ) THEN RETURN NULL; END IF;
          RAISE EXCEPTION 'historical discovery evidence cannot be truncated';
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_discovery_reject_sealed_insert() RETURNS trigger AS $$
        DECLARE plan_sealed timestamptz;
        BEGIN
          IF TG_TABLE_NAME='market_historicaltimestampinventory' THEN
            SELECT p.sealed_at INTO plan_sealed
              FROM market_historicaldiscoverychunk c
              JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
              WHERE c.id=NEW.chunk_id;
          ELSE
            SELECT p.sealed_at INTO plan_sealed
              FROM market_historicaldiscoveryattempt a
              JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
              JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
              WHERE a.id=NEW.attempt_id;
          END IF;
          IF plan_sealed IS NOT NULL THEN
            RAISE EXCEPTION 'registered discovery plans reject new evidence';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_plan() RETURNS trigger AS $$
        DECLARE approval_count integer; registration_count integer; chunk_count integer;
                materialized_manifest jsonb; source record;
        BEGIN
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'historical discovery plans are append-only';
          END IF;
          IF TG_OP='UPDATE' THEN
            IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL
               OR ROW(OLD.identity,OLD.version,OLD.source_id,OLD.purpose,OLD.environment,
                      OLD.phase1_spec_hash,OLD.phase1_manifest_hash,OLD.superseded_data_identity,
                      OLD.declared_chunk_count,OLD.canonical_request_manifest,
                      OLD.canonical_request_manifest_sha256,OLD.payload,OLD.sha256,OLD.created_at)
                  IS DISTINCT FROM
                  ROW(NEW.identity,NEW.version,NEW.source_id,NEW.purpose,NEW.environment,
                      NEW.phase1_spec_hash,NEW.phase1_manifest_hash,NEW.superseded_data_identity,
                      NEW.declared_chunk_count,NEW.canonical_request_manifest,
                      NEW.canonical_request_manifest_sha256,NEW.payload,NEW.sha256,NEW.created_at)
            THEN RAISE EXCEPTION 'only governed discovery-plan sealing is permitted'; END IF;
            SELECT count(*) INTO approval_count FROM market_historicaldiscoveryapproval
              WHERE plan_id=NEW.id;
            SELECT count(*) INTO registration_count FROM market_historicaldiscoveryregistration
              WHERE plan_id=NEW.id AND registered_at=NEW.sealed_at;
            IF approval_count<>1 OR registration_count<>1 THEN
              RAISE EXCEPTION 'discovery sealing requires atomic approval and registration';
            END IF;
            SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
              'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
              'canonical_request',c.canonical_request,
              'canonical_request_sha256',c.canonical_request_sha256) ORDER BY c.ordinal),'[]')
              INTO chunk_count,materialized_manifest FROM market_historicaldiscoverychunk c
              WHERE c.plan_id=NEW.id;
            IF chunk_count<>NEW.declared_chunk_count
               OR materialized_manifest IS DISTINCT FROM NEW.canonical_request_manifest THEN
              RAISE EXCEPTION 'materialized discovery requests do not equal declared manifest';
            END IF;
            RETURN NEW;
          END IF;
          SELECT * INTO STRICT source FROM market_sourceregistry WHERE id=NEW.source_id;
          IF NEW.sealed_at IS NOT NULL
             OR length(btrim(NEW.identity))=0
             OR NEW.version!~'^phase-2b1r-discovery-v[1-9][0-9]*$'
             OR NEW.purpose<>'provider_timestamp_inventory_discovery'
             OR NEW.environment<>'practice'
             OR NEW.phase1_spec_hash<>'47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash<>'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR NEW.superseded_data_identity<>'oanda-ba-ny17-friday-v1'
             OR jsonb_typeof(NEW.canonical_request_manifest)<>'array'
             OR jsonb_array_length(NEW.canonical_request_manifest)<>NEW.declared_chunk_count
             OR NEW.canonical_request_manifest_sha256<>
                market_sha256(NEW.canonical_request_manifest)
             OR NEW.sha256<>market_sha256(NEW.payload)
             OR NEW.payload->>'discovery_contract'<>
                'oanda-provider-observed-timestamp-discovery'
             OR NEW.payload->>'discovery_version'<>NEW.version
             OR NEW.payload->>'identity'<>NEW.identity
             OR NEW.payload->>'purpose'<>NEW.purpose
             OR NEW.payload->>'environment'<>NEW.environment
             OR NEW.payload->>'phase1_spec_hash'<>NEW.phase1_spec_hash
             OR NEW.payload->>'phase1_manifest_hash'<>NEW.phase1_manifest_hash
             OR NEW.payload->>'superseded_data_identity'<>NEW.superseded_data_identity
             OR NEW.payload->>'replacement_data_identity'<>
                'oanda-ba-ny17-friday-provider-observed-v1'
             OR (NEW.payload->>'declared_chunk_count')::integer<>NEW.declared_chunk_count
             OR NEW.payload->'requests'<>NEW.canonical_request_manifest
             OR NEW.payload->>'canonical_request_manifest_sha256'<>
                NEW.canonical_request_manifest_sha256
             OR NEW.payload->'source'<>
                '{"name":"OANDA v20","governed_identity":"oanda-v20-market-candles-v1"}'::jsonb
             OR source.name<>'OANDA v20' OR source.tier<>'established' OR NOT source.enabled
             OR source.acquisition_method<>'v20 REST API' OR source.llm_processing_allowed
          THEN RAISE EXCEPTION 'discovery plan conflicts with canonical contract'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_chunk() RETURNS trigger AS $$
        DECLARE plan record; instrument_code text; item jsonb; expected_request jsonb;
                request_hash text; expected_key text;
        BEGIN
          SELECT * INTO STRICT plan FROM market_historicaldiscoveryplan WHERE id=NEW.plan_id;
          SELECT i.code INTO STRICT instrument_code
            FROM market_instrument i WHERE i.id=NEW.instrument_id;
          item := plan.canonical_request_manifest->(NEW.ordinal-1);
          expected_request := jsonb_build_object(
            'instrument',instrument_code,'granularity',NEW.granularity,
            'from',market_discovery_timestamp(NEW.requested_from),
            'to',market_discovery_timestamp(NEW.requested_to),
            'price','BA','price_component','COMBINED_BID_ASK','smooth',false,
            'dailyAlignment',17,'alignmentTimezone','America/New_York',
            'weeklyAlignment','Friday','includeFirst',true);
          request_hash := market_sha256(expected_request);
          expected_key := market_sha256(jsonb_build_object(
            'discovery_contract','oanda-provider-observed-timestamp-discovery',
            'discovery_version',plan.version,
            'source_identity','oanda-v20-market-candles-v1','instrument',instrument_code,
            'granularity',NEW.granularity,
            'requested_from',market_discovery_timestamp(NEW.requested_from),
            'requested_to',market_discovery_timestamp(NEW.requested_to),
            'canonical_request_sha256',request_hash));
          IF plan.sealed_at IS NOT NULL OR NEW.ordinal<1 OR NEW.ordinal>plan.declared_chunk_count
             OR NEW.requested_from>=NEW.requested_to
             OR NEW.canonical_request IS DISTINCT FROM expected_request
             OR NEW.canonical_request_sha256 IS DISTINCT FROM request_hash
             OR NEW.logical_key IS DISTINCT FROM expected_key
             OR item IS DISTINCT FROM jsonb_build_object(
                'ordinal',NEW.ordinal,'logical_discovery_key',expected_key,
                'canonical_request',expected_request,'canonical_request_sha256',request_hash)
          THEN RAISE EXCEPTION 'discovery chunk conflicts with declared request manifest'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_attempt() RETURNS trigger AS $$
        DECLARE lineage record; expected_key text; expected_parameters jsonb;
                next_attempt integer;
        BEGIN
          SELECT c.*,p.source_id,p.sealed_at,i.code,r.dataset_version_id AS run_dataset,
                 r.source_id AS run_source,r.instrument_id AS run_instrument,
                 r.granularity AS run_granularity,r.requested_from AS run_from,
                 r.requested_to AS run_to,r.parameters,r.request_manifest_hash,r.status
            INTO STRICT lineage
            FROM market_historicaldiscoverychunk c
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_instrument i ON i.id=c.instrument_id
            JOIN market_ingestionrun r ON r.id=NEW.ingestion_run_id
            WHERE c.id=NEW.chunk_id;
          expected_key := 'historical-discovery-attempt:'||lineage.logical_key||':'||NEW.attempt_number;
          expected_parameters := jsonb_build_object(
            'purpose','provider_timestamp_inventory_discovery',
            'logical_discovery_key',lineage.logical_key,
            'canonical_request_sha256',lineage.canonical_request_sha256) || lineage.canonical_request;
          SELECT coalesce(max(attempt_number),0)+1 INTO next_attempt
            FROM market_historicaldiscoveryattempt WHERE chunk_id=NEW.chunk_id;
          IF lineage.sealed_at IS NOT NULL OR NEW.attempt_number<>next_attempt
             OR NEW.idempotency_key<>expected_key OR lineage.run_dataset IS NOT NULL
             OR lineage.run_source<>lineage.source_id
             OR lineage.run_instrument<>lineage.instrument_id
             OR lineage.run_granularity<>lineage.granularity
             OR lineage.run_from<>lineage.requested_from OR lineage.run_to<>lineage.requested_to
             OR lineage.parameters IS DISTINCT FROM expected_parameters
             OR lineage.request_manifest_hash<>market_sha256(jsonb_build_object(
                'purpose','provider_timestamp_inventory_discovery',
                'attempt_idempotency_key',expected_key))
             OR lineage.status<>'running'
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt a
               JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
               WHERE a.chunk_id=NEW.chunk_id AND r.status IN ('running','succeeded'))
          THEN RAISE EXCEPTION 'discovery attempt conflicts with canonical run lineage'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_observation() RETURNS trigger AS $$
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
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_inventory_deferred() RETURNS trigger AS $$
        DECLARE inv record; observation_count integer; timestamp_hash text;
                structural_hash text; semantic_hash text; inventory_key bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaltimestampinventory' THEN
            inventory_key := NEW.id;
          ELSE
            inventory_key := NEW.inventory_id;
          END IF;
          SELECT i.*,c.logical_key,c.canonical_request_sha256,c.plan_id,a.chunk_id AS attempt_chunk,
                 r.status,r.fetched_count,r.stored_count,r.rejected_count,p.sealed_at
            INTO STRICT inv FROM market_historicaltimestampinventory i
            JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_historicaldiscoveryattempt a ON a.id=i.accepted_attempt_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE i.id=inventory_key;
          SELECT count(*),market_sha256(coalesce(jsonb_agg(
                   market_discovery_timestamp(o.timestamp) ORDER BY o.timestamp),'[]')),
                 market_sha256(coalesce(jsonb_agg(jsonb_build_object(
                   'timestamp',market_discovery_timestamp(o.timestamp),'complete',o.complete,
                   'volume',o.volume,'bid_present',o.bid_present,'ask_present',o.ask_present)
                   ORDER BY o.timestamp),'[]'))
            INTO observation_count,timestamp_hash,structural_hash
            FROM market_historicaltimestampobservation o WHERE o.inventory_id=inv.id;
          semantic_hash := market_sha256(jsonb_build_object(
            'logical_discovery_key',inv.logical_key,
            'canonical_request_sha256',inv.canonical_request_sha256,
            'observation_count',observation_count,'timestamp_set_sha256',timestamp_hash,
            'structural_observation_sha256',structural_hash));
          IF inv.chunk_id<>inv.attempt_chunk
             OR inv.status<>'succeeded' OR observation_count<1
             OR inv.observation_count<>observation_count
             OR inv.fetched_count<>observation_count OR inv.stored_count<>observation_count
             OR inv.rejected_count<>0 OR inv.timestamp_set_sha256<>timestamp_hash
             OR inv.structural_observation_sha256<>structural_hash
             OR inv.semantic_inventory_sha256<>semantic_hash
          THEN RAISE EXCEPTION 'discovery inventory does not reconstruct'; END IF;
          RETURN NULL;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_provider_evidence() RETURNS trigger AS $$
        DECLARE lineage record; expected_unavailable jsonb; event_payload jsonb;
                expected_operational_hash text; event_count integer;
        BEGIN
          SELECT c.canonical_request_sha256,c.plan_id,c.logical_key,p.sealed_at,
                 r.id AS run_id,r.status,r.request_manifest_hash,r.started_at,r.finished_at,
                 r.failure_reason,i.code,a.attempt_number,a.idempotency_key
            INTO STRICT lineage FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            JOIN market_instrument i ON i.id=c.instrument_id WHERE a.id=NEW.attempt_id;
          SELECT coalesce(jsonb_agg(field ORDER BY field),'[]') INTO expected_unavailable
            FROM (VALUES
              ('canonical_request_sha256',NEW.canonical_request_sha256 IS NULL),
              ('endpoint_identity',NEW.endpoint_identity IS NULL),
              ('environment',NEW.environment IS NULL),('http_method',NEW.http_method IS NULL),
              ('http_status',NEW.http_status IS NULL),
              ('provider_request_id',NEW.provider_request_id IS NULL)) AS missing(field,value)
            WHERE value;
          SELECT count(*) INTO event_count
            FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=NEW.attempt_id::text
              AND audit.event_type IN ('market.historical_discovery_succeeded',
                                       'market.historical_discovery_failed');
          SELECT audit.payload INTO event_payload FROM market_auditevent audit
            WHERE audit.subject_type='HistoricalDiscoveryAttempt'
              AND audit.subject_id=NEW.attempt_id::text
              AND audit.event_type IN ('market.historical_discovery_succeeded',
                                       'market.historical_discovery_failed') LIMIT 1;
          expected_operational_hash := market_sha256(jsonb_build_object(
            'logical_discovery_key',lineage.logical_key,
            'attempt_number',lineage.attempt_number,
            'attempt_idempotency_key',lineage.idempotency_key,
            'run_id',lineage.run_id,
            'run_request_manifest_hash',lineage.request_manifest_hash,
            'canonical_request_sha256',NEW.canonical_request_sha256,
            'endpoint_identity',NEW.endpoint_identity,'environment',NEW.environment,
            'http_method',NEW.http_method,'http_status',NEW.http_status,
            'provider_request_id',NEW.provider_request_id,
            'unavailable_fields',NEW.unavailable_fields,
            'started_at',market_discovery_operational_timestamp(lineage.started_at),
            'finished_at',market_discovery_operational_timestamp(lineage.finished_at),
            'terminal_status',lineage.status,
            'failure_code',nullif(lineage.failure_reason,''),
            'terminal_event_sha256',NEW.terminal_event_sha256));
          IF lineage.status='running'
             OR event_count<>1 OR event_payload->>'event_sha256'<>NEW.terminal_event_sha256
             OR market_sha256(event_payload-'event_sha256')<>NEW.terminal_event_sha256
             OR NEW.operational_evidence_sha256<>expected_operational_hash
             OR NEW.unavailable_fields IS DISTINCT FROM expected_unavailable
             OR (NEW.provider_request_id IS NOT NULL AND
                 NEW.provider_request_id!~'^[A-Za-z0-9._:-]{1,200}$')
             OR (NEW.http_status IS NOT NULL AND
                 (NEW.http_status<100 OR NEW.http_status>599))
             OR (NEW.canonical_request_sha256 IS NOT NULL AND
                 NEW.canonical_request_sha256<>lineage.canonical_request_sha256)
             OR (NEW.endpoint_identity IS NOT NULL AND NEW.endpoint_identity<>
                 'oanda-v20-practice:GET:/v3/instruments/'||lineage.code||'/candles')
             OR (NEW.http_method IS NOT NULL AND NEW.http_method<>'GET')
             OR (NEW.environment IS NOT NULL AND NEW.environment<>'practice')
             OR (lineage.status='succeeded' AND (expected_unavailable<>'[]'::jsonb
                 OR NEW.http_status<>200))
          THEN RAISE EXCEPTION 'discovery provider evidence is invalid'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_audit_insert() RETURNS trigger AS $$
        DECLARE lineage record; evidence record; existing_count integer; payload_key_count integer;
                expected_provider jsonb; expected_success_diagnostics jsonb; diagnostics jsonb;
                expected_event_body jsonb; expected_event jsonb;
                expected_event_type text; expected_error_code text; expected_stage text;
                expected_diagnostics jsonb;
        BEGIN
          IF NEW.subject_type<>'HistoricalDiscoveryAttempt'
             AND NEW.event_type NOT LIKE 'market.historical_discovery_%%'
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
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_discovery_audit_reject_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.subject_type='HistoricalDiscoveryAttempt'
             OR OLD.event_type LIKE 'market.historical_discovery_%%'
             OR (TG_OP='UPDATE' AND (NEW.subject_type='HistoricalDiscoveryAttempt'
                 OR NEW.event_type LIKE 'market.historical_discovery_%%'))
          THEN RAISE EXCEPTION 'discovery terminal audit events are immutable'; END IF;
          RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_discovery_audit_reject_truncate() RETURNS trigger AS $$
        BEGIN
          IF current_database() LIKE 'test\_%%' ESCAPE '\'
             AND EXISTS(
               SELECT 1 FROM pg_locks locks
               WHERE locks.pid=pg_backend_pid() AND locks.granted
                 AND locks.mode='AccessExclusiveLock'
                 AND locks.relation='auth_permission'::regclass
             ) THEN RETURN NULL; END IF;
          IF EXISTS(SELECT 1 FROM market_auditevent
                    WHERE subject_type='HistoricalDiscoveryAttempt'
                       OR event_type LIKE 'market.historical_discovery_%%')
          THEN RAISE EXCEPTION 'discovery terminal audit events cannot be truncated'; END IF;
          RETURN NULL;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_terminal_run() RETURNS trigger AS $$
        DECLARE discovery_attempt_id bigint; evidence_count integer; event_count integer;
        BEGIN
          IF NEW.parameters->>'purpose' IS DISTINCT FROM 'provider_timestamp_inventory_discovery'
          THEN RETURN NULL; END IF;
          SELECT id INTO discovery_attempt_id FROM market_historicaldiscoveryattempt
            WHERE ingestion_run_id=NEW.id;
          IF discovery_attempt_id IS NULL THEN
            RAISE EXCEPTION 'discovery run lacks its one-to-one attempt';
          END IF;
          IF NEW.status='running' THEN RETURN NULL; END IF;
          SELECT count(*) INTO evidence_count FROM market_historicaldiscoveryproviderevidence
            WHERE attempt_id=discovery_attempt_id;
          SELECT count(*) INTO event_count FROM market_auditevent
            WHERE subject_type='HistoricalDiscoveryAttempt'
              AND subject_id=discovery_attempt_id::text
              AND event_type IN ('market.historical_discovery_succeeded',
                                 'market.historical_discovery_failed');
          IF evidence_count<>1 OR event_count<>1 OR NEW.finished_at IS NULL
             OR (NEW.status='succeeded' AND (NEW.failure_reason<>'' OR NEW.fetched_count<>NEW.stored_count
                 OR NEW.rejected_count<>0))
             OR (NEW.status='failed' AND (NEW.failure_reason='' OR NEW.stored_count<>0
                 OR NEW.rejected_count<>NEW.fetched_count))
          THEN RAISE EXCEPTION 'terminal discovery run lacks atomic evidence'; END IF;
          RETURN NULL;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_discovery_seal_deferred() RETURNS trigger AS $$
        DECLARE plan_key bigint; plan_row record; approval_row record; registration_row record;
                permission_ok boolean; chunk_count integer; inventory_count integer;
                running_count integer; chunk_manifest jsonb; semantic_manifest jsonb;
                operational_manifest jsonb; chunk_hash text; semantic_hash text; operational_hash text;
                approver_username text; expected_approval jsonb; expected_registration jsonb;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key := NEW.id;
          ELSE
            plan_key := NEW.plan_id;
          END IF;
          SELECT * INTO STRICT plan_row FROM market_historicaldiscoveryplan WHERE id=plan_key;
          SELECT * INTO approval_row FROM market_historicaldiscoveryapproval WHERE plan_id=plan_key;
          SELECT * INTO registration_row FROM market_historicaldiscoveryregistration WHERE plan_id=plan_key;
          IF approval_row.id IS NULL OR registration_row.id IS NULL OR plan_row.sealed_at IS NULL THEN
            RAISE EXCEPTION 'approval, registration and sealing must commit atomically';
          END IF;
          SELECT u.is_active AND (u.is_superuser OR EXISTS(
            SELECT 1 FROM auth_user_user_permissions up JOIN auth_permission perm ON perm.id=up.permission_id
             JOIN django_content_type ct ON ct.id=perm.content_type_id
             WHERE up.user_id=u.id AND perm.codename='approve_historical_discovery'
               AND ct.app_label='market' AND ct.model='historicaldiscoveryplan') OR EXISTS(
            SELECT 1 FROM auth_user_groups ug JOIN auth_group_permissions gp ON gp.group_id=ug.group_id
             JOIN auth_permission perm ON perm.id=gp.permission_id
             JOIN django_content_type ct ON ct.id=perm.content_type_id
             WHERE ug.user_id=u.id AND perm.codename='approve_historical_discovery'
               AND ct.app_label='market' AND ct.model='historicaldiscoveryplan'))
            INTO permission_ok FROM auth_user u WHERE u.id=approval_row.approved_by_id;
          SELECT username INTO approver_username FROM auth_user
            WHERE id=approval_row.approved_by_id;
          SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
              'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
              'canonical_request',c.canonical_request,
              'canonical_request_sha256',c.canonical_request_sha256) ORDER BY c.ordinal),'[]'),
              coalesce(jsonb_agg(jsonb_build_object('logical_discovery_key',c.logical_key,
              'semantic_inventory_sha256',inv.semantic_inventory_sha256) ORDER BY c.ordinal)
              FILTER (WHERE inv.id IS NOT NULL),'[]'),count(inv.id)
            INTO chunk_count,chunk_manifest,semantic_manifest,inventory_count
            FROM market_historicaldiscoverychunk c LEFT JOIN market_historicaltimestampinventory inv
              ON inv.chunk_id=c.id WHERE c.plan_id=plan_key;
          SELECT count(*) INTO running_count FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE c.plan_id=plan_key AND r.status='running';
          SELECT coalesce(jsonb_agg(e.operational_evidence_sha256
                   ORDER BY c.ordinal,a.attempt_number),'[]') INTO operational_manifest
            FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_historicaldiscoveryproviderevidence e ON e.attempt_id=a.id
            WHERE c.plan_id=plan_key;
          chunk_hash:=market_sha256(chunk_manifest); semantic_hash:=market_sha256(semantic_manifest);
          operational_hash:=market_sha256(operational_manifest);
          expected_approval:=jsonb_build_object(
            'identity','failed-break-phase-2b1r-discovery-approval-v1',
            'plan_sha256',plan_row.sha256,
            'global_semantic_inventory_sha256',semantic_hash,
            'accepted_operational_evidence_set_sha256',operational_hash,
            'cross_series_report_sha256',registration_row.cross_series_report_sha256,
            'approved_by',approver_username,
            'approved_at',market_discovery_operational_timestamp(approval_row.approved_at));
          expected_registration:=jsonb_build_object(
            'plan_sha256',plan_row.sha256,'approval_sha256',approval_row.sha256,
            'ordered_chunk_manifest_sha256',chunk_hash,
            'global_semantic_inventory_sha256',semantic_hash,
            'accepted_operational_evidence_set_sha256',operational_hash,
            'cross_series_report_sha256',registration_row.cross_series_report_sha256,
            'registered_at',market_discovery_operational_timestamp(registration_row.registered_at));
          IF NOT coalesce(permission_ok,false) OR chunk_count<>plan_row.declared_chunk_count
             OR inventory_count<>chunk_count OR running_count<>0
             OR chunk_manifest<>plan_row.canonical_request_manifest
             OR approval_row.global_semantic_inventory_sha256<>semantic_hash
             OR approval_row.accepted_operational_evidence_set_sha256<>operational_hash
             OR approval_row.payload IS DISTINCT FROM expected_approval
             OR approval_row.sha256 IS DISTINCT FROM market_sha256(expected_approval)
             OR registration_row.approval_id<>approval_row.id
             OR registration_row.ordered_chunk_manifest_sha256<>chunk_hash
             OR registration_row.global_semantic_inventory_sha256<>semantic_hash
             OR registration_row.accepted_operational_evidence_set_sha256<>operational_hash
             OR approval_row.payload->>'cross_series_report_sha256' IS DISTINCT FROM
                registration_row.cross_series_report_sha256
             OR registration_row.payload IS DISTINCT FROM expected_registration
             OR registration_row.report_sha256 IS DISTINCT FROM
                market_sha256(expected_registration)
             OR registration_row.registered_at<>plan_row.sealed_at
          THEN RAISE EXCEPTION 'discovery seal does not reconstruct'; END IF;
          RETURN NULL;
        END $$ LANGUAGE plpgsql;

        CREATE TRIGGER market_discovery_plan_validate BEFORE INSERT OR UPDATE OR DELETE
          ON market_historicaldiscoveryplan FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_plan();
        CREATE TRIGGER market_discovery_chunk_validate BEFORE INSERT
          ON market_historicaldiscoverychunk FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_chunk();
        CREATE TRIGGER market_discovery_attempt_validate BEFORE INSERT
          ON market_historicaldiscoveryattempt FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_attempt();
        CREATE TRIGGER market_discovery_observation_validate BEFORE INSERT
          ON market_historicaltimestampobservation FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_observation();
        CREATE TRIGGER market_discovery_provider_unsealed BEFORE INSERT
          ON market_historicaldiscoveryproviderevidence FOR EACH ROW
          EXECUTE FUNCTION market_discovery_reject_sealed_insert();
        CREATE TRIGGER market_discovery_inventory_unsealed BEFORE INSERT
          ON market_historicaltimestampinventory FOR EACH ROW
          EXECUTE FUNCTION market_discovery_reject_sealed_insert();
        CREATE CONSTRAINT TRIGGER market_discovery_provider_validate AFTER INSERT
          ON market_historicaldiscoveryproviderevidence DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_provider_evidence();
        CREATE TRIGGER market_discovery_audit_validate BEFORE INSERT
          ON market_auditevent FOR EACH ROW
          EXECUTE FUNCTION market_validate_discovery_audit_insert();
        CREATE TRIGGER market_discovery_audit_immutable BEFORE UPDATE OR DELETE
          ON market_auditevent FOR EACH ROW
          EXECUTE FUNCTION market_discovery_audit_reject_mutation();
        CREATE TRIGGER market_discovery_audit_no_truncate BEFORE TRUNCATE
          ON market_auditevent FOR EACH STATEMENT
          EXECUTE FUNCTION market_discovery_audit_reject_truncate();

        CREATE CONSTRAINT TRIGGER market_discovery_inventory_reconstruct
          AFTER INSERT ON market_historicaltimestampinventory DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_inventory_deferred();
        CREATE CONSTRAINT TRIGGER market_discovery_run_terminal
          AFTER INSERT OR UPDATE ON market_ingestionrun DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_terminal_run();
        CREATE CONSTRAINT TRIGGER market_discovery_approval_atomic
          AFTER INSERT ON market_historicaldiscoveryapproval DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_seal_deferred();
        CREATE CONSTRAINT TRIGGER market_discovery_registration_atomic
          AFTER INSERT ON market_historicaldiscoveryregistration DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_seal_deferred();
        CREATE CONSTRAINT TRIGGER market_discovery_plan_seal_atomic
          AFTER UPDATE ON market_historicaldiscoveryplan DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION market_validate_discovery_seal_deferred();
        """
    )
    for table in DISCOVERY_TABLES[:-1]:
        schema_editor.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION market_discovery_reject_mutation();"
        )
    for table in DISCOVERY_TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER {table}_reject_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION market_discovery_reject_truncate();"
        )


def require_empty_discovery(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT "
            + " OR ".join(f"EXISTS(SELECT 1 FROM {table})" for table in DISCOVERY_TABLES)
            + " OR EXISTS(SELECT 1 FROM market_ingestionrun "
            "WHERE parameters->>'purpose'='provider_timestamp_inventory_discovery')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("provider-observed discovery evidence prohibits migration reversal")


def remove_discovery_governance(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    require_empty_discovery(apps, schema_editor)
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS market_discovery_run_terminal ON market_ingestionrun;"
        "DROP TRIGGER IF EXISTS market_discovery_audit_validate ON market_auditevent;"
        "DROP TRIGGER IF EXISTS market_discovery_audit_immutable ON market_auditevent;"
        "DROP TRIGGER IF EXISTS market_discovery_audit_no_truncate ON market_auditevent;"
        "DROP TRIGGER IF EXISTS market_discovery_approval_atomic "
        "ON market_historicaldiscoveryapproval;"
        "DROP TRIGGER IF EXISTS market_discovery_registration_atomic "
        "ON market_historicaldiscoveryregistration;"
        "DROP TRIGGER IF EXISTS market_discovery_plan_seal_atomic "
        "ON market_historicaldiscoveryplan;"
        "DROP TRIGGER IF EXISTS market_discovery_inventory_reconstruct "
        "ON market_historicaltimestampinventory;"
        "DROP TRIGGER IF EXISTS market_discovery_observation_reconstruct "
        "ON market_historicaltimestampobservation;"
        "DROP TRIGGER IF EXISTS market_discovery_plan_validate "
        "ON market_historicaldiscoveryplan;"
        "DROP TRIGGER IF EXISTS market_discovery_chunk_validate "
        "ON market_historicaldiscoverychunk;"
        "DROP TRIGGER IF EXISTS market_discovery_attempt_validate "
        "ON market_historicaldiscoveryattempt;"
        "DROP TRIGGER IF EXISTS market_discovery_observation_validate "
        "ON market_historicaltimestampobservation;"
        "DROP TRIGGER IF EXISTS market_discovery_provider_validate "
        "ON market_historicaldiscoveryproviderevidence;"
        "DROP TRIGGER IF EXISTS market_discovery_provider_unsealed "
        "ON market_historicaldiscoveryproviderevidence;"
        "DROP TRIGGER IF EXISTS market_discovery_inventory_unsealed "
        "ON market_historicaltimestampinventory;"
    )
    for table in DISCOVERY_TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_reject_truncate ON {table};")
    for table in DISCOVERY_TABLES[:-1]:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS market_validate_discovery_terminal_run();"
        "DROP FUNCTION IF EXISTS market_discovery_audit_reject_mutation();"
        "DROP FUNCTION IF EXISTS market_discovery_audit_reject_truncate();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_audit_insert();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_seal_deferred();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_provider_evidence();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_inventory_deferred();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_observation();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_attempt();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_chunk();"
        "DROP FUNCTION IF EXISTS market_validate_discovery_plan();"
        "DROP FUNCTION IF EXISTS market_discovery_reject_truncate();"
        "DROP FUNCTION IF EXISTS market_discovery_reject_sealed_insert();"
        "DROP FUNCTION IF EXISTS market_discovery_reject_mutation();"
        "DROP FUNCTION IF EXISTS market_discovery_operational_timestamp(timestamptz);"
        "DROP FUNCTION IF EXISTS market_discovery_timestamp(timestamptz);"
    )


class Migration(migrations.Migration):
    atomic = True
    dependencies = [
        ("market", "0012_operation_aware_historical_dataset"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RunPython(preflight_discovery_schema, migrations.RunPython.noop),
        migrations.CreateModel(
            name="HistoricalDiscoveryChunk",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("ordinal", models.PositiveIntegerField()),
                (
                    "granularity",
                    models.CharField(
                        choices=[("W", "Weekly"), ("D", "Daily"), ("H1", "Hourly")], max_length=3
                    ),
                ),
                ("requested_from", models.DateTimeField()),
                ("requested_to", models.DateTimeField()),
                ("canonical_request", models.JSONField()),
                ("canonical_request_sha256", models.CharField(max_length=64)),
                ("logical_key", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "instrument",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="market.instrument"
                    ),
                ),
            ],
            options={"ordering": ("plan", "ordinal")},
        ),
        migrations.CreateModel(
            name="HistoricalDiscoveryAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("attempt_number", models.PositiveIntegerField()),
                ("idempotency_key", models.CharField(max_length=200, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ingestion_run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="historical_discovery_attempt",
                        to="market.ingestionrun",
                    ),
                ),
                (
                    "chunk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attempts",
                        to="market.historicaldiscoverychunk",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HistoricalDiscoveryPlan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("identity", models.CharField(max_length=160)),
                ("version", models.CharField(max_length=80)),
                ("purpose", models.CharField(max_length=80)),
                ("environment", models.CharField(max_length=12)),
                ("phase1_spec_hash", models.CharField(max_length=64)),
                ("phase1_manifest_hash", models.CharField(max_length=64)),
                ("superseded_data_identity", models.CharField(max_length=160)),
                ("declared_chunk_count", models.PositiveIntegerField()),
                ("canonical_request_manifest", models.JSONField()),
                ("canonical_request_manifest_sha256", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                ("sha256", models.CharField(max_length=64, unique=True)),
                ("sealed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="market.sourceregistry"
                    ),
                ),
            ],
            options={
                "permissions": [
                    ("approve_historical_discovery", "Can approve historical timestamp discovery")
                ]
            },
        ),
        migrations.AddField(
            model_name="historicaldiscoverychunk",
            name="plan",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="chunks",
                to="market.historicaldiscoveryplan",
            ),
        ),
        migrations.CreateModel(
            name="HistoricalDiscoveryApproval",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("global_semantic_inventory_sha256", models.CharField(max_length=64)),
                ("accepted_operational_evidence_set_sha256", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                ("sha256", models.CharField(max_length=64, unique=True)),
                ("approved_at", models.DateTimeField()),
                (
                    "approved_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "plan",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval",
                        to="market.historicaldiscoveryplan",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HistoricalDiscoveryProviderEvidence",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("endpoint_identity", models.CharField(blank=True, max_length=240, null=True)),
                ("http_method", models.CharField(blank=True, max_length=8, null=True)),
                ("environment", models.CharField(blank=True, max_length=12, null=True)),
                ("http_status", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("provider_request_id", models.CharField(blank=True, max_length=200, null=True)),
                (
                    "canonical_request_sha256",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("unavailable_fields", models.JSONField(default=list)),
                ("terminal_event_sha256", models.CharField(max_length=64)),
                ("operational_evidence_sha256", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "attempt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="provider_evidence",
                        to="market.historicaldiscoveryattempt",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HistoricalDiscoveryRegistration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("ordered_chunk_manifest_sha256", models.CharField(max_length=64)),
                ("global_semantic_inventory_sha256", models.CharField(max_length=64)),
                ("accepted_operational_evidence_set_sha256", models.CharField(max_length=64)),
                ("cross_series_report_sha256", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                ("report_sha256", models.CharField(max_length=64, unique=True)),
                ("registered_at", models.DateTimeField()),
                (
                    "approval",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration",
                        to="market.historicaldiscoveryapproval",
                    ),
                ),
                (
                    "plan",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration",
                        to="market.historicaldiscoveryplan",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HistoricalTimestampInventory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("observation_count", models.PositiveIntegerField()),
                ("timestamp_set_sha256", models.CharField(max_length=64)),
                ("structural_observation_sha256", models.CharField(max_length=64)),
                ("semantic_inventory_sha256", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "accepted_attempt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory",
                        to="market.historicaldiscoveryattempt",
                    ),
                ),
                (
                    "chunk",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory",
                        to="market.historicaldiscoverychunk",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="HistoricalTimestampObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("timestamp", models.DateTimeField()),
                ("complete", models.BooleanField()),
                ("volume", models.PositiveIntegerField()),
                ("bid_present", models.BooleanField()),
                ("ask_present", models.BooleanField()),
                (
                    "inventory",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="observations",
                        to="market.historicaltimestampinventory",
                    ),
                ),
            ],
            options={"ordering": ("inventory", "timestamp")},
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoveryattempt",
            constraint=models.UniqueConstraint(
                fields=("chunk", "attempt_number"),
                name="unique_historical_discovery_attempt_number",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoveryattempt",
            constraint=models.CheckConstraint(
                condition=models.Q(("attempt_number__gte", 1)),
                name="historical_discovery_attempt_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoveryplan",
            constraint=models.UniqueConstraint(
                fields=("identity", "version"), name="unique_historical_discovery_plan_version"
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoveryplan",
            constraint=models.CheckConstraint(
                condition=models.Q(("declared_chunk_count__gte", 1)),
                name="historical_discovery_plan_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoverychunk",
            constraint=models.UniqueConstraint(
                fields=("plan", "ordinal"), name="unique_historical_discovery_chunk_ordinal"
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoverychunk",
            constraint=models.UniqueConstraint(
                fields=("plan", "instrument", "granularity", "requested_from", "requested_to"),
                name="unique_historical_discovery_request",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoverychunk",
            constraint=models.CheckConstraint(
                condition=models.Q(("ordinal__gte", 1)),
                name="historical_discovery_ordinal_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaldiscoverychunk",
            constraint=models.CheckConstraint(
                condition=models.Q(("requested_from__lt", models.F("requested_to"))),
                name="historical_discovery_increasing_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaltimestampinventory",
            constraint=models.CheckConstraint(
                condition=models.Q(("observation_count__gte", 1)),
                name="historical_timestamp_inventory_nonempty",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaltimestampobservation",
            constraint=models.UniqueConstraint(
                fields=("inventory", "timestamp"), name="unique_historical_timestamp_observation"
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaltimestampobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(("complete", True)),
                name="historical_discovery_observation_complete",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaltimestampobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(("bid_present", True)),
                name="historical_discovery_observation_has_bid",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicaltimestampobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(("ask_present", True)),
                name="historical_discovery_observation_has_ask",
            ),
        ),
        migrations.RunPython(install_discovery_governance, remove_discovery_governance),
    ]
