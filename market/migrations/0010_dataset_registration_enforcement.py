import hashlib
import json

import django.db.models.deletion
from django.db import migrations, models

PHASE1_SPEC = "47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd"
PHASE1_MANIFEST = "f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882"
INSTRUMENTS = ["AUD_USD", "EUR_GBP", "EUR_USD", "GBP_USD", "USD_CAD", "USD_JPY"]
GRANULARITIES = ["D", "H1", "W"]
ALIGNMENT = {
    "timezone": "America/New_York",
    "daily_hour": 17,
    "weekly_day": "Friday",
    "smooth": False,
}


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def preflight(apps, schema_editor):
    """Reject every malformed row that could have been written during partial 0009 rollout."""
    Plan = apps.get_model("market", "HistoricalDatasetPlan")
    Chunk = apps.get_model("market", "HistoricalIngestionChunk")
    Attempt = apps.get_model("market", "HistoricalIngestionAttempt")
    IngestionRun = apps.get_model("market", "IngestionRun")
    Dataset = apps.get_model("market", "DatasetVersion")

    if IngestionRun.objects.exclude(
        status__in=("running", "succeeded", "failed", "quarantined")
    ).exists():
        raise RuntimeError("ingestion run has an unsupported status")
    for plan in Plan.objects.select_related(
        "source", "strategy_version__strategyparametermanifest"
    ):
        parameter = plan.strategy_version.strategyparametermanifest
        if (
            plan.instruments != INSTRUMENTS
            or plan.granularities != GRANULARITIES
            or plan.alignment != ALIGNMENT
            or plan.price_component != "COMBINED_BID_ASK"
            or not plan.complete_only
            or plan.phase1_spec_hash != PHASE1_SPEC
            or plan.phase1_manifest_hash != PHASE1_MANIFEST
            or plan.strategy_version.content_hash != PHASE1_MANIFEST
            or plan.source.name != "OANDA v20"
            or not plan.source.enabled
            or plan.strategy_version.data_identity != plan.identity
            or plan.strategy_version.pair_metadata
            != {
                "instruments": [
                    "EUR_USD",
                    "GBP_USD",
                    "EUR_GBP",
                    "USD_CAD",
                    "USD_JPY",
                    "AUD_USD",
                ]
            }
            or parameter.sha256 != PHASE1_MANIFEST
            or parameter.phase1_spec_hash != PHASE1_SPEC
            or parameter.phase1_manifest_hash != PHASE1_MANIFEST
            or plan.payload.get("instruments") != plan.instruments
            or plan.payload.get("granularities") != plan.granularities
            or plan.payload.get("ranges") != plan.ranges
            or plan.payload.get("alignment") != plan.alignment
            or plan.payload.get("price_component") != plan.price_component
            or plan.payload.get("complete_only") != plan.complete_only
            or plan.payload.get("chunk_size") != plan.chunk_size
            or plan.sha256 != _hash(plan.payload)
        ):
            raise RuntimeError("partial 0009 contains an invalid historical plan")
    plan_hashes = set(Plan.objects.values_list("sha256", flat=True))
    if any(
        dataset.manifest.get("historical_plan_sha256") not in plan_hashes
        or dataset.manifest_sha256 != _hash(dataset.manifest)
        for dataset in Dataset.objects.filter(manifest__has_key="historical_plan_sha256")
    ):
        raise RuntimeError("partial 0009 contains an invalid historical dataset manifest")
    for chunk in Chunk.objects.select_related("plan", "dataset_version", "instrument"):
        request_hash = _hash(chunk.canonical_request)
        logical_key = _hash(
            {
                "plan_sha256": chunk.plan.sha256,
                "dataset_manifest_sha256": chunk.dataset_version.manifest_sha256,
                "canonical_request_sha256": request_hash,
            }
        )
        if (
            chunk.dataset_version.manifest.get("historical_plan_sha256") != chunk.plan.sha256
            or chunk.instrument.code not in chunk.plan.instruments
            or chunk.granularity not in chunk.plan.granularities
            or chunk.canonical_request_sha256 != request_hash
            or chunk.logical_key != logical_key
            or chunk.canonical_request.get("instrument") != chunk.instrument.code
            or chunk.canonical_request.get("granularity") != chunk.granularity
            or chunk.canonical_request.get("from") != chunk.requested_from.isoformat()
            or chunk.canonical_request.get("to") != chunk.requested_to.isoformat()
        ):
            raise RuntimeError("partial 0009 contains an invalid historical chunk")
    for attempt in Attempt.objects.select_related("chunk__plan", "ingestion_run"):
        chunk, run = attempt.chunk, attempt.ingestion_run
        prior_numbers = list(
            Attempt.objects.filter(chunk=chunk, attempt_number__lte=attempt.attempt_number)
            .order_by("attempt_number")
            .values_list("attempt_number", flat=True)
        )
        if (
            prior_numbers != list(range(1, attempt.attempt_number + 1))
            or attempt.idempotency_key
            != f"failed-break-ingestion-attempt:{chunk.logical_key}:{attempt.attempt_number}"
            or run.source_id != chunk.plan.source_id
            or run.dataset_version_id != chunk.dataset_version_id
            or run.instrument_id != chunk.instrument_id
            or run.granularity != chunk.granularity
            or run.requested_from != chunk.requested_from
            or run.requested_to != chunk.requested_to
            or run.parameters != chunk.canonical_request
            or run.request_manifest_hash != _hash({"attempt": attempt.idempotency_key})
        ):
            raise RuntimeError("partial 0009 contains invalid attempt lineage")


def create_governance_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    schema_editor.execute(
        """
        DO $$ BEGIN
          IF to_regprocedure('digest(bytea,text)') IS NULL THEN
            RAISE EXCEPTION 'Phase 2B requires pgcrypto digest(bytea,text)';
          END IF;
        END $$;

        CREATE FUNCTION market_canonical_json(value jsonb) RETURNS text AS $$
        DECLARE result text;
        BEGIN
          CASE jsonb_typeof(value)
          WHEN 'object' THEN
            SELECT '{' || coalesce(string_agg(to_jsonb(key)::text || ':' ||
              market_canonical_json(val), ',' ORDER BY key), '') || '}' INTO result
              FROM jsonb_each(value) AS item(key, val);
          WHEN 'array' THEN
            SELECT '[' || coalesce(string_agg(market_canonical_json(val), ',' ORDER BY ord), '') || ']'
              INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS item(val, ord);
          ELSE result := value::text;
          END CASE;
          RETURN result;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE STRICT;
        CREATE FUNCTION market_sha256(value jsonb) RETURNS text AS $$
          SELECT encode(digest(convert_to(market_canonical_json(value), 'UTF8'), 'sha256'), 'hex')
        $$ LANGUAGE sql IMMUTABLE STRICT;

        CREATE FUNCTION market_registered_completion(value timestamptz, granularity text)
        RETURNS timestamptz AS $$
        DECLARE local_value timestamp;
        BEGIN
          local_value := value AT TIME ZONE 'America/New_York';
          RETURN CASE granularity WHEN 'H1' THEN value + interval '1 hour'
            WHEN 'D' THEN (local_value + interval '1 day') AT TIME ZONE 'America/New_York'
            WHEN 'W' THEN (local_value + interval '7 days') AT TIME ZONE 'America/New_York'
          END;
        END $$ LANGUAGE plpgsql IMMUTABLE STRICT;

        CREATE FUNCTION market_expected_count(range_start timestamptz, range_end timestamptz,
                                               granularity text) RETURNS integer AS $$
        DECLARE current_value timestamptz := range_start; local_value timestamp;
                next_local timestamp; result integer := 0; completion timestamptz;
        BEGIN
          IF range_start >= range_end OR granularity NOT IN ('H1','D','W') THEN RETURN -1; END IF;
          WHILE current_value < range_end LOOP
            local_value := current_value AT TIME ZONE 'America/New_York';
            IF extract(minute from local_value)<>0 OR extract(second from local_value)<>0
               OR (granularity='H1' AND NOT (extract(isodow from local_value) BETWEEN 1 AND 4
                    OR (extract(isodow from local_value)=5 AND local_value::time<time '17:00')
                    OR (extract(isodow from local_value)=7 AND local_value::time>=time '17:00')))
               OR (granularity='D' AND (local_value::time<>time '17:00'
                    OR extract(isodow from local_value) NOT IN (1,2,3,4,7)))
               OR (granularity='W' AND (local_value::time<>time '17:00'
                    OR extract(isodow from local_value)<>5)) THEN RETURN -1;
            END IF;
            completion := market_registered_completion(current_value, granularity);
            IF completion > range_end THEN RETURN -1; END IF;
            result := result + 1;
            IF granularity='H1' THEN
              current_value := current_value + interval '1 hour';
              next_local := current_value AT TIME ZONE 'America/New_York';
              IF extract(isodow from next_local)=5 AND next_local::time=time '17:00' THEN
                current_value := (next_local + interval '2 days') AT TIME ZONE 'America/New_York';
              END IF;
            ELSIF granularity='D' THEN
              next_local := local_value + CASE WHEN extract(isodow from local_value)=4
                                                THEN interval '3 days' ELSE interval '1 day' END;
              current_value := next_local AT TIME ZONE 'America/New_York';
            ELSE
              current_value := (local_value + interval '7 days') AT TIME ZONE 'America/New_York';
            END IF;
          END LOOP;
          IF completion IS DISTINCT FROM range_end THEN RETURN -1; END IF;
          RETURN result;
        END $$ LANGUAGE plpgsql IMMUTABLE STRICT;

        CREATE FUNCTION market_phase2b_immutable() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION '%% is append-only', TG_TABLE_NAME; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_historical_plan_immutable BEFORE UPDATE OR DELETE
          ON market_historicaldatasetplan FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();
        CREATE TRIGGER market_historical_chunk_immutable BEFORE UPDATE OR DELETE
          ON market_historicalingestionchunk FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();
        CREATE TRIGGER market_historical_attempt_immutable BEFORE UPDATE OR DELETE
          ON market_historicalingestionattempt FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();
        CREATE TRIGGER market_dataset_registration_immutable BEFORE UPDATE OR DELETE
          ON market_datasetregistration FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();

        CREATE FUNCTION market_validate_historical_plan() RETURNS trigger AS $$
        DECLARE strategy record; parameter record; source record; item record;
        BEGIN
          SELECT * INTO STRICT strategy FROM research_strategyversion WHERE id = NEW.strategy_version_id;
          SELECT * INTO STRICT parameter FROM research_strategyparametermanifest
            WHERE strategy_version_id = NEW.strategy_version_id;
          SELECT * INTO STRICT source FROM market_sourceregistry WHERE id=NEW.source_id;
          IF NEW.instruments <> '["AUD_USD","EUR_GBP","EUR_USD","GBP_USD","USD_CAD","USD_JPY"]'::jsonb
             OR NEW.granularities <> '["D","H1","W"]'::jsonb
             OR NEW.alignment <> '{"timezone":"America/New_York","daily_hour":17,"weekly_day":"Friday","smooth":false}'::jsonb
             OR NEW.price_component <> 'COMBINED_BID_ASK' OR NOT NEW.complete_only
             OR NEW.phase1_spec_hash <> '47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash <> 'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR source.name<>'OANDA v20' OR NOT source.enabled
             OR strategy.content_hash <> NEW.phase1_manifest_hash
             OR strategy.data_identity <> NEW.identity
             OR strategy.pair_metadata <> '{"instruments":["EUR_USD","GBP_USD","EUR_GBP","USD_CAD","USD_JPY","AUD_USD"]}'::jsonb
             OR parameter.sha256 <> NEW.phase1_manifest_hash
             OR parameter.phase1_spec_hash <> NEW.phase1_spec_hash
             OR parameter.phase1_manifest_hash <> NEW.phase1_manifest_hash
             OR NEW.payload->>'identity' <> NEW.identity
             OR (NEW.payload->>'source_id')::bigint <> NEW.source_id
             OR (NEW.payload->>'strategy_version_id')::bigint <> NEW.strategy_version_id
             OR NEW.payload->'instruments' <> NEW.instruments
             OR NEW.payload->'granularities' <> NEW.granularities
             OR NEW.payload->'ranges' <> NEW.ranges OR NEW.payload->'alignment' <> NEW.alignment
             OR NEW.payload->>'price_component' <> NEW.price_component
             OR (NEW.payload->>'complete_only')::boolean IS DISTINCT FROM NEW.complete_only
             OR (NEW.payload->>'chunk_size')::integer <> NEW.chunk_size
             OR NEW.payload->>'phase1_spec_hash' <> NEW.phase1_spec_hash
             OR NEW.payload->>'phase1_manifest_hash' <> NEW.phase1_manifest_hash
             OR NOT NEW.ranges ?& array['D','H1','W']
             OR NEW.sha256 <> market_sha256(NEW.payload) THEN
            RAISE EXCEPTION 'historical plan conflicts with the frozen canonical contract';
          END IF;
          FOR item IN SELECT * FROM jsonb_each(NEW.ranges) LOOP
            IF item.key NOT IN ('D','H1','W')
               OR (item.value->>'expected_count_per_instrument')::integer < 1
               OR (item.value->>'expected_count_per_instrument')::integer <>
                  market_expected_count((item.value->>'from')::timestamptz,
                                        (item.value->>'to')::timestamptz,item.key)
               OR (item.key='H1' AND (item.value->>'to')::timestamptz<>
                    timestamptz '2019-01-01 04:00:00+00')
               OR (item.key='D' AND (item.value->>'to')::timestamptz<>
                    timestamptz '2018-12-31 22:00:00+00')
               OR (item.key='W' AND (item.value->>'to')::timestamptz<>
                    timestamptz '2018-12-28 22:00:00+00')
            THEN RAISE EXCEPTION 'historical plan range is not the frozen calendar range'; END IF;
          END LOOP;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_historical_plan_validate BEFORE INSERT ON market_historicaldatasetplan
          FOR EACH ROW EXECUTE FUNCTION market_validate_historical_plan();

        CREATE FUNCTION market_validate_historical_chunk() RETURNS trigger AS $$
        DECLARE plan record; dataset record; instrument_code text; expected jsonb; request_hash text; expected_key text;
        BEGIN
          SELECT * INTO STRICT plan FROM market_historicaldatasetplan WHERE id = NEW.plan_id;
          SELECT * INTO STRICT dataset FROM market_datasetversion WHERE id = NEW.dataset_version_id;
          SELECT instrument.code INTO STRICT instrument_code FROM market_instrument instrument
            WHERE instrument.id = NEW.instrument_id;
          expected := jsonb_build_object('instrument', instrument_code, 'granularity', NEW.granularity,
            'from', to_char(NEW.requested_from AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')||'+00:00',
            'to', to_char(NEW.requested_to AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')||'+00:00',
            'price', 'BA', 'price_component', 'COMBINED_BID_ASK', 'smooth', false,
            'dailyAlignment', 17, 'alignmentTimezone', 'America/New_York',
            'weeklyAlignment', 'Friday', 'complete_only', true);
          request_hash := market_sha256(expected);
          expected_key := market_sha256(jsonb_build_object('plan_sha256', plan.sha256,
            'dataset_manifest_sha256', dataset.manifest_sha256,
            'canonical_request_sha256', request_hash));
          IF dataset.manifest->>'historical_plan_sha256' IS DISTINCT FROM plan.sha256
             OR NOT plan.instruments @> to_jsonb(instrument_code)
             OR NOT plan.granularities @> to_jsonb(NEW.granularity)
             OR NEW.canonical_request <> expected OR NEW.canonical_request_sha256 <> request_hash
             OR NEW.logical_key <> expected_key OR NEW.requested_from >= NEW.requested_to
             OR market_expected_count(NEW.requested_from,NEW.requested_to,NEW.granularity)
                NOT BETWEEN 1 AND 4999
             OR NEW.requested_to >= timestamptz '2019-01-01 05:00:00+00'
             OR NEW.requested_from < (plan.ranges->NEW.granularity->>'from')::timestamptz
             OR NEW.requested_to > (plan.ranges->NEW.granularity->>'to')::timestamptz
             OR EXISTS (SELECT 1 FROM market_datasetregistration WHERE dataset_version_id=NEW.dataset_version_id)
          THEN RAISE EXCEPTION 'historical chunk conflicts with canonical plan lineage'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_historical_chunk_validate BEFORE INSERT ON market_historicalingestionchunk
          FOR EACH ROW EXECUTE FUNCTION market_validate_historical_chunk();

        CREATE FUNCTION market_ingestion_run_enforce() RETURNS trigger AS $$
        DECLARE historical boolean; has_attempt boolean;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            historical := NEW.dataset_version_id IS NOT NULL AND EXISTS
              (SELECT 1 FROM market_datasetversion WHERE id=NEW.dataset_version_id
               AND manifest ? 'historical_plan_sha256');
            IF historical AND (EXISTS (SELECT 1 FROM market_datasetregistration
                 WHERE dataset_version_id=NEW.dataset_version_id)
              OR NOT EXISTS (SELECT 1 FROM market_historicalingestionchunk c
                 JOIN market_historicaldatasetplan p ON p.id=c.plan_id
                 WHERE c.dataset_version_id=NEW.dataset_version_id AND p.source_id=NEW.source_id
                 AND c.instrument_id=NEW.instrument_id AND c.granularity=NEW.granularity
                 AND c.requested_from=NEW.requested_from AND c.requested_to=NEW.requested_to
                 AND c.canonical_request=NEW.parameters))
            THEN RAISE EXCEPTION 'historical run lacks open canonical chunk lineage'; END IF;
            RETURN NEW;
          END IF;
          has_attempt := EXISTS (SELECT 1 FROM market_historicalingestionattempt
                                  WHERE ingestion_run_id=OLD.id);
          IF TG_OP='DELETE' THEN
            IF OLD.status <> 'running' OR has_attempt THEN
              RAISE EXCEPTION 'ingestion runs with audit lineage cannot be deleted';
            END IF; RETURN OLD;
          END IF;
          IF OLD.status <> 'running' OR NEW.status NOT IN ('succeeded','failed','quarantined')
             OR NEW.finished_at IS NULL OR NEW.source_id<>OLD.source_id
             OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id
             OR NEW.instrument_id<>OLD.instrument_id OR NEW.granularity<>OLD.granularity
             OR NEW.requested_from<>OLD.requested_from OR NEW.requested_to<>OLD.requested_to
             OR NEW.parameters IS DISTINCT FROM OLD.parameters
             OR NEW.request_manifest_hash<>OLD.request_manifest_hash OR NEW.started_at<>OLD.started_at
             OR (NEW.status='succeeded' AND has_attempt AND NOT EXISTS
                 (SELECT 1 FROM market_ingestionmanifest WHERE ingestion_run_id=NEW.id))
          THEN RAISE EXCEPTION 'ingestion run may make one valid terminal transition only'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_ingestion_run_enforce BEFORE INSERT OR UPDATE OR DELETE ON market_ingestionrun
          FOR EACH ROW EXECUTE FUNCTION market_ingestion_run_enforce();

        CREATE FUNCTION market_validate_historical_attempt() RETURNS trigger AS $$
        DECLARE chunk record; run record; plan_source bigint; next_number integer;
        BEGIN
          SELECT * INTO STRICT chunk FROM market_historicalingestionchunk WHERE id=NEW.chunk_id FOR UPDATE;
          SELECT * INTO STRICT run FROM market_ingestionrun WHERE id=NEW.ingestion_run_id;
          SELECT source_id INTO STRICT plan_source FROM market_historicaldatasetplan WHERE id=chunk.plan_id;
          SELECT coalesce(max(attempt_number),0)+1 INTO next_number FROM market_historicalingestionattempt
            WHERE chunk_id=NEW.chunk_id;
          IF NEW.attempt_number<>next_number OR run.status<>'running' OR run.source_id<>plan_source
             OR run.dataset_version_id<>chunk.dataset_version_id OR run.instrument_id<>chunk.instrument_id
             OR run.granularity<>chunk.granularity OR run.requested_from<>chunk.requested_from
             OR run.requested_to<>chunk.requested_to OR run.parameters IS DISTINCT FROM chunk.canonical_request
             OR run.request_manifest_hash<>market_sha256(jsonb_build_object('attempt', NEW.idempotency_key))
             OR NEW.idempotency_key<>'failed-break-ingestion-attempt:'||chunk.logical_key||':'||NEW.attempt_number
             OR EXISTS (SELECT 1 FROM market_datasetregistration WHERE dataset_version_id=chunk.dataset_version_id)
          THEN RAISE EXCEPTION 'historical attempt conflicts with deterministic lineage'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_historical_attempt_validate BEFORE INSERT ON market_historicalingestionattempt
          FOR EACH ROW EXECUTE FUNCTION market_validate_historical_attempt();

        CREATE FUNCTION market_historical_evidence_insert() RETURNS trigger AS $$
        BEGIN
          IF NEW.dataset_version_id IS NOT NULL AND EXISTS
            (SELECT 1 FROM market_datasetregistration WHERE dataset_version_id=NEW.dataset_version_id)
          THEN RAISE EXCEPTION 'registered historical dataset is sealed'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE FUNCTION market_historical_manifest_insert() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM market_datasetregistration
                     WHERE dataset_version_id=NEW.dataset_version_id)
          THEN RAISE EXCEPTION 'registered historical dataset is sealed'; END IF;
          IF EXISTS (SELECT 1 FROM market_datasetversion WHERE id=NEW.dataset_version_id
                     AND manifest ? 'historical_plan_sha256') AND (NOT EXISTS
             (SELECT 1 FROM market_historicalingestionattempt a JOIN market_historicalingestionchunk c
                ON c.id=a.chunk_id WHERE a.ingestion_run_id=NEW.ingestion_run_id
                AND c.dataset_version_id=NEW.dataset_version_id)
             OR NEW.sha256<>market_sha256(NEW.payload))
          THEN RAISE EXCEPTION 'historical manifest conflicts with attempt lineage or hash'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_ingestion_manifest_historical_validate BEFORE INSERT ON market_ingestionmanifest
          FOR EACH ROW EXECUTE FUNCTION market_historical_manifest_insert();
        CREATE TRIGGER market_conflict_historical_seal BEFORE INSERT ON market_candleconflict
          FOR EACH ROW EXECUTE FUNCTION market_historical_evidence_insert();
        CREATE TRIGGER market_incident_historical_seal BEFORE INSERT ON market_dataqualityincident
          FOR EACH ROW EXECUTE FUNCTION market_historical_evidence_insert();

        DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;
        DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();
        CREATE FUNCTION market_governed_candle_reject_mutation() RETURNS trigger AS $$
        DECLARE chunk record;
        BEGIN
          IF TG_OP='DELETE' THEN IF OLD.dataset_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'governed dataset candles are append-only'; END IF; RETURN OLD; END IF;
          IF TG_OP='UPDATE' THEN IF OLD.dataset_version_id IS NOT NULL OR NEW.dataset_version_id IS NOT NULL
            THEN RAISE EXCEPTION 'governed dataset candles must be inserted and are append-only'; END IF;
            RETURN NEW; END IF;
          IF NEW.dataset_version_id IS NULL THEN RETURN NEW; END IF;
          IF EXISTS (SELECT 1 FROM market_datasetregistration WHERE dataset_version_id=NEW.dataset_version_id)
            THEN RAISE EXCEPTION 'registered historical dataset is sealed'; END IF;
          IF EXISTS (SELECT 1 FROM market_datasetversion WHERE id=NEW.dataset_version_id
                     AND manifest ? 'historical_plan_sha256') THEN
            SELECT c.* INTO chunk FROM market_historicalingestionattempt a
              JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
              WHERE a.ingestion_run_id=NEW.ingestion_run_id;
            IF chunk.id IS NULL OR chunk.dataset_version_id<>NEW.dataset_version_id
               OR chunk.instrument_id<>NEW.instrument_id OR chunk.granularity<>NEW.granularity
               OR NOT NEW.complete OR NEW.timestamp<chunk.requested_from
               OR NEW.timestamp>=chunk.requested_to
               OR market_expected_count(NEW.timestamp,
                    market_registered_completion(NEW.timestamp,NEW.granularity),NEW.granularity)<>1
               OR market_registered_completion(NEW.timestamp,NEW.granularity)
                    >= timestamptz '2019-01-01 05:00:00+00'
            THEN RAISE EXCEPTION 'historical candle conflicts with chunk lineage or boundary'; END IF;
          END IF; RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_governed_candle_append_only BEFORE INSERT OR UPDATE OR DELETE ON market_candle
          FOR EACH ROW EXECUTE FUNCTION market_governed_candle_reject_mutation();

        CREATE FUNCTION market_validate_dataset_registration() RETURNS trigger AS $$
        DECLARE plan record; dataset record; expected_logical text; expected_attempt text;
                expected_manifest text; expected_series jsonb; expected_candle_keys text;
                expected_candle_payloads text; configuration jsonb; report jsonb;
        BEGIN
          LOCK TABLE market_historicalingestionchunk, market_historicalingestionattempt,
            market_ingestionrun, market_ingestionmanifest, market_candle IN SHARE ROW EXCLUSIVE MODE;
          SELECT * INTO STRICT plan FROM market_historicaldatasetplan WHERE id=NEW.plan_id;
          SELECT * INTO STRICT dataset FROM market_datasetversion WHERE id=NEW.dataset_version_id;
          SELECT market_sha256(coalesce(jsonb_agg(c.logical_key ORDER BY i.code,c.granularity,c.requested_from),'[]'))
            INTO expected_logical FROM market_historicalingestionchunk c
            JOIN market_instrument i ON i.id=c.instrument_id
            WHERE c.plan_id=NEW.plan_id AND c.dataset_version_id=NEW.dataset_version_id;
          SELECT market_sha256(coalesce(jsonb_agg(a.idempotency_key ORDER BY i.code,c.granularity,c.requested_from),'[]')),
                 market_sha256(coalesce(jsonb_agg(m.sha256 ORDER BY m.sha256),'[]'))
            INTO expected_attempt, expected_manifest
            FROM market_historicalingestionchunk c JOIN market_historicalingestionattempt a ON a.chunk_id=c.id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id AND r.status='succeeded'
            JOIN market_ingestionmanifest m ON m.ingestion_run_id=r.id
            JOIN market_instrument i ON i.id=c.instrument_id
            WHERE c.plan_id=NEW.plan_id AND c.dataset_version_id=NEW.dataset_version_id;
          SELECT jsonb_agg(jsonb_build_object('series',instrument||':'||granularity,
                   'range',plan.ranges->granularity,
                   'row_count',(plan.ranges->granularity->>'expected_count_per_instrument')::integer)
                   ORDER BY instrument_order,granularity_order)
            INTO expected_series
            FROM jsonb_array_elements_text(plan.instruments) WITH ORDINALITY instruments(instrument,instrument_order)
            CROSS JOIN jsonb_array_elements_text(plan.granularities) WITH ORDINALITY granularities(granularity,granularity_order);
          SELECT encode(digest(convert_to(coalesce(string_agg(market_canonical_json(jsonb_build_array(
                    i.code,c.granularity,to_char(c.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00')),
                    '' ORDER BY i.code,c.granularity,c.timestamp),''),'UTF8'),'sha256'),'hex'),
                 encode(digest(convert_to(coalesce(string_agg(market_canonical_json(jsonb_build_array(
                    i.code,c.granularity,to_char(c.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00',
                    c.complete,c.volume,to_char(c.bid_open,'FM999999999990.000000'),
                    to_char(c.bid_high,'FM999999999990.000000'),to_char(c.bid_low,'FM999999999990.000000'),
                    to_char(c.bid_close,'FM999999999990.000000'),to_char(c.ask_open,'FM999999999990.000000'),
                    to_char(c.ask_high,'FM999999999990.000000'),to_char(c.ask_low,'FM999999999990.000000'),
                    to_char(c.ask_close,'FM999999999990.000000'))),
                    '' ORDER BY i.code,c.granularity,c.timestamp),''),'UTF8'),'sha256'),'hex')
            INTO expected_candle_keys,expected_candle_payloads FROM market_candle c
            JOIN market_instrument i ON i.id=c.instrument_id WHERE c.dataset_version_id=NEW.dataset_version_id;
          configuration := jsonb_build_object('identity','failed-break-historical-dataset-registration-v1',
            'plan_sha256',plan.sha256,'dataset_manifest_sha256',dataset.manifest_sha256,
            'price_component','COMBINED_BID_ASK','logical_chunk_set_hash',NEW.logical_chunk_set_hash);
          report := jsonb_build_object('configuration_sha256',NEW.configuration_sha256,
            'series_manifest',NEW.series_manifest,'row_counts',NEW.row_counts,
            'first_last_timestamps',NEW.first_last_timestamps,'missingness',NEW.missingness,
            'conflict_count',NEW.conflict_count,'incident_count',NEW.incident_count,
            'logical_chunk_set_hash',NEW.logical_chunk_set_hash,
            'successful_attempt_set_hash',NEW.successful_attempt_set_hash,
            'ingestion_manifest_set_hash',NEW.ingestion_manifest_set_hash,
            'candle_key_hash',NEW.candle_key_hash,'candle_payload_hash',NEW.candle_payload_hash);
          IF dataset.manifest_sha256<>market_sha256(dataset.manifest)
             OR dataset.manifest->>'historical_plan_sha256' IS DISTINCT FROM plan.sha256
             OR dataset.manifest->>'strategy_manifest_sha256'<>plan.phase1_manifest_hash
             OR dataset.manifest->'partition'<>'{"name":"development","start_year":2010,"end_year":2018}'::jsonb
             OR dataset.manifest->'instruments'<>plan.instruments
             OR dataset.manifest->'granularities'<>plan.granularities
             OR dataset.manifest->'alignment'<>plan.alignment
             OR dataset.manifest->>'price_component'<>'COMBINED_BID_ASK'
             OR (dataset.manifest->>'complete_only')::boolean IS DISTINCT FROM true
             OR jsonb_array_length(dataset.manifest->'required_ranges')<>18
             OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(plan.instruments) instrument
                  CROSS JOIN jsonb_array_elements_text(plan.granularities) granularity
                  WHERE (SELECT count(*) FROM jsonb_array_elements(dataset.manifest->'required_ranges') item
                    WHERE item->>'instrument'=instrument.value AND item->>'granularity'=granularity.value
                      AND (item->>'start')::timestamptz=(plan.ranges->granularity.value->>'from')::timestamptz
                      AND (item->>'end')::timestamptz=(plan.ranges->granularity.value->>'to')::timestamptz)<>1)
             OR NEW.logical_chunk_set_hash<>expected_logical OR NEW.successful_attempt_set_hash<>expected_attempt
             OR NEW.ingestion_manifest_set_hash<>expected_manifest
             OR NEW.series_manifest<>expected_series
             OR (SELECT count(*) FROM jsonb_object_keys(NEW.row_counts))<>18
             OR (SELECT count(*) FROM jsonb_object_keys(NEW.first_last_timestamps))<>18
             OR (SELECT count(*) FROM jsonb_object_keys(NEW.missingness))<>18
             OR NEW.candle_key_hash<>expected_candle_keys
             OR NEW.candle_payload_hash<>expected_candle_payloads
             OR NEW.configuration_sha256<>market_sha256(configuration) OR NEW.report_sha256<>market_sha256(report)
             OR NEW.conflict_count<>0 OR NEW.incident_count<>0
             OR EXISTS (SELECT 1 FROM market_ingestionrun r WHERE r.dataset_version_id=NEW.dataset_version_id
                  AND (r.status='running' OR NOT EXISTS (SELECT 1 FROM market_historicalingestionattempt a
                                                        WHERE a.ingestion_run_id=r.id)))
             OR EXISTS (SELECT 1 FROM market_historicalingestionchunk c WHERE c.plan_id=NEW.plan_id
                  AND c.dataset_version_id=NEW.dataset_version_id AND
                  (SELECT count(*) FROM market_historicalingestionattempt a JOIN market_ingestionrun r
                   ON r.id=a.ingestion_run_id JOIN market_ingestionmanifest m ON m.ingestion_run_id=r.id
                   WHERE a.chunk_id=c.id AND r.status='succeeded')<>1)
             OR EXISTS (SELECT 1 FROM market_historicalingestionchunk c
                  JOIN market_historicalingestionattempt a ON a.chunk_id=c.id
                  JOIN market_ingestionrun r ON r.id=a.ingestion_run_id AND r.status='succeeded'
                  WHERE c.plan_id=NEW.plan_id AND c.dataset_version_id=NEW.dataset_version_id
                    AND (r.fetched_count<>market_expected_count(c.requested_from,c.requested_to,c.granularity)
                      OR r.stored_count<>market_expected_count(c.requested_from,c.requested_to,c.granularity)
                      OR (SELECT count(*) FROM market_candle candle
                          WHERE candle.ingestion_run_id=r.id)<>
                         market_expected_count(c.requested_from,c.requested_to,c.granularity)
                      OR (SELECT min(candle.timestamp) FROM market_candle candle
                          WHERE candle.ingestion_run_id=r.id)<>c.requested_from
                      OR market_registered_completion((SELECT max(candle.timestamp) FROM market_candle candle
                          WHERE candle.ingestion_run_id=r.id),c.granularity)<>c.requested_to))
             OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(plan.instruments) instrument
                  CROSS JOIN jsonb_array_elements_text(plan.granularities) granularity
                  WHERE (SELECT coalesce(sum(market_expected_count(c.requested_from,c.requested_to,c.granularity)),0)
                         FROM market_historicalingestionchunk c JOIN market_instrument i ON i.id=c.instrument_id
                         WHERE c.plan_id=NEW.plan_id AND c.dataset_version_id=NEW.dataset_version_id
                           AND i.code=instrument.value AND c.granularity=granularity.value)
                        <>(plan.ranges->granularity.value->>'expected_count_per_instrument')::integer
                     OR (SELECT min(c.requested_from) FROM market_historicalingestionchunk c
                         JOIN market_instrument i ON i.id=c.instrument_id WHERE c.plan_id=NEW.plan_id
                         AND c.dataset_version_id=NEW.dataset_version_id AND i.code=instrument.value
                         AND c.granularity=granularity.value)<>
                        (plan.ranges->granularity.value->>'from')::timestamptz
                     OR (SELECT max(c.requested_to) FROM market_historicalingestionchunk c
                         JOIN market_instrument i ON i.id=c.instrument_id WHERE c.plan_id=NEW.plan_id
                         AND c.dataset_version_id=NEW.dataset_version_id AND i.code=instrument.value
                         AND c.granularity=granularity.value)<>
                        (plan.ranges->granularity.value->>'to')::timestamptz
                     OR (SELECT count(*) FROM market_candle c JOIN market_instrument i ON i.id=c.instrument_id
                         WHERE c.dataset_version_id=NEW.dataset_version_id AND i.code=instrument.value
                         AND c.granularity=granularity.value)<>
                        (plan.ranges->granularity.value->>'expected_count_per_instrument')::integer
                     OR (NEW.row_counts->>(instrument.value||':'||granularity.value))::integer<>
                        (plan.ranges->granularity.value->>'expected_count_per_instrument')::integer
                     OR (NEW.first_last_timestamps->(instrument.value||':'||granularity.value)->>'first')::timestamptz<>
                        (plan.ranges->granularity.value->>'from')::timestamptz
                     OR (NEW.first_last_timestamps->(instrument.value||':'||granularity.value)->>'last')::timestamptz<>
                        (SELECT max(c.timestamp) FROM market_candle c JOIN market_instrument i ON i.id=c.instrument_id
                         WHERE c.dataset_version_id=NEW.dataset_version_id AND i.code=instrument.value
                         AND c.granularity=granularity.value)
                     OR (NEW.missingness->>(instrument.value||':'||granularity.value))::integer<>0)
             OR EXISTS (SELECT 1 FROM market_candleconflict WHERE dataset_version_id=NEW.dataset_version_id)
             OR EXISTS (SELECT 1 FROM market_dataqualityincident WHERE dataset_version_id=NEW.dataset_version_id)
             OR EXISTS (SELECT 1 FROM market_candle c JOIN market_ingestionrun r ON r.id=c.ingestion_run_id
                  LEFT JOIN market_ingestionmanifest m ON m.ingestion_run_id=r.id
                  LEFT JOIN market_historicalingestionattempt a ON a.ingestion_run_id=r.id
                  LEFT JOIN market_historicalingestionchunk h ON h.id=a.chunk_id
                  WHERE c.dataset_version_id=NEW.dataset_version_id AND (r.status<>'succeeded'
                    OR r.dataset_version_id<>NEW.dataset_version_id OR m.dataset_version_id<>NEW.dataset_version_id
                    OR h.dataset_version_id<>NEW.dataset_version_id OR h.instrument_id<>c.instrument_id
                    OR h.granularity<>c.granularity OR c.timestamp<h.requested_from
                    OR c.timestamp>=h.requested_to))
             OR (SELECT count(*) FROM market_candle WHERE dataset_version_id=NEW.dataset_version_id)
                <> (SELECT coalesce(sum((value)::integer),0) FROM jsonb_each_text(NEW.row_counts))
             OR EXISTS (SELECT 1 FROM jsonb_each_text(NEW.missingness) WHERE value::integer<>0)
          THEN RAISE EXCEPTION 'dataset is not eligible for exact immutable registration'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_dataset_registration_validate BEFORE INSERT ON market_datasetregistration
          FOR EACH ROW EXECUTE FUNCTION market_validate_dataset_registration();
        """
    )


def drop_governance_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM market_historicaldatasetplan)
               OR EXISTS(SELECT 1 FROM market_historicalingestionchunk)
               OR EXISTS(SELECT 1 FROM market_historicalingestionattempt)
               OR EXISTS(SELECT 1 FROM market_datasetregistration)
               OR EXISTS(SELECT 1 FROM market_datasetversion WHERE manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_ingestionrun r JOIN market_datasetversion d
                    ON d.id=r.dataset_version_id WHERE d.manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_ingestionmanifest m JOIN market_datasetversion d
                    ON d.id=m.dataset_version_id WHERE d.manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_candle c JOIN market_datasetversion d
                    ON d.id=c.dataset_version_id WHERE d.manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_candleconflict c JOIN market_datasetversion d
                    ON d.id=c.dataset_version_id WHERE d.manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_dataqualityincident q JOIN market_datasetversion d
                    ON d.id=q.dataset_version_id WHERE d.manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_auditevent
                    WHERE event_type LIKE 'market.historical_attempt_%%')"""
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("Phase 2B rollback is forbidden after acquisition evidence exists")
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS market_dataset_registration_validate ON market_datasetregistration;
        DROP FUNCTION IF EXISTS market_validate_dataset_registration();
        DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;
        DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();
        DROP TRIGGER IF EXISTS market_incident_historical_seal ON market_dataqualityincident;
        DROP TRIGGER IF EXISTS market_conflict_historical_seal ON market_candleconflict;
        DROP TRIGGER IF EXISTS market_ingestion_manifest_historical_validate ON market_ingestionmanifest;
        DROP FUNCTION IF EXISTS market_historical_manifest_insert();
        DROP FUNCTION IF EXISTS market_historical_evidence_insert();
        DROP TRIGGER IF EXISTS market_historical_attempt_validate ON market_historicalingestionattempt;
        DROP FUNCTION IF EXISTS market_validate_historical_attempt();
        DROP TRIGGER IF EXISTS market_ingestion_run_enforce ON market_ingestionrun;
        DROP FUNCTION IF EXISTS market_ingestion_run_enforce();
        DROP TRIGGER IF EXISTS market_historical_chunk_validate ON market_historicalingestionchunk;
        DROP FUNCTION IF EXISTS market_validate_historical_chunk();
        DROP TRIGGER IF EXISTS market_historical_plan_validate ON market_historicaldatasetplan;
        DROP FUNCTION IF EXISTS market_validate_historical_plan();
        DROP TRIGGER IF EXISTS market_dataset_registration_immutable ON market_datasetregistration;
        DROP TRIGGER IF EXISTS market_historical_attempt_immutable ON market_historicalingestionattempt;
        DROP TRIGGER IF EXISTS market_historical_chunk_immutable ON market_historicalingestionchunk;
        DROP TRIGGER IF EXISTS market_historical_plan_immutable ON market_historicaldatasetplan;
        DROP FUNCTION IF EXISTS market_phase2b_immutable();
        DROP FUNCTION IF EXISTS market_expected_count(timestamptz,timestamptz,text);
        DROP FUNCTION IF EXISTS market_registered_completion(timestamptz,text);
        DROP FUNCTION IF EXISTS market_sha256(jsonb);
        DROP FUNCTION IF EXISTS market_canonical_json(jsonb);
        """
    )
    from importlib import import_module

    import_module("market.migrations.0008_reject_governed_candle_promotion").apply_trigger(
        apps, schema_editor
    )


class Migration(migrations.Migration):
    dependencies = [("market", "0009_historical_dataset_governance")]
    operations = [
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.CreateModel(
            name="DatasetRegistration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("series_manifest", models.JSONField()),
                ("row_counts", models.JSONField()),
                ("first_last_timestamps", models.JSONField()),
                ("missingness", models.JSONField()),
                ("conflict_count", models.PositiveIntegerField()),
                ("incident_count", models.PositiveIntegerField()),
                ("logical_chunk_set_hash", models.CharField(max_length=64)),
                ("successful_attempt_set_hash", models.CharField(max_length=64)),
                ("ingestion_manifest_set_hash", models.CharField(max_length=64)),
                ("candle_key_hash", models.CharField(max_length=64)),
                ("candle_payload_hash", models.CharField(max_length=64)),
                ("configuration_sha256", models.CharField(max_length=64)),
                ("report_sha256", models.CharField(max_length=64, unique=True)),
                ("registered_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dataset_version",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration",
                        to="market.datasetversion",
                    ),
                ),
                (
                    "plan",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration",
                        to="market.historicaldatasetplan",
                    ),
                ),
            ],
            options={"abstract": False},
        ),
        migrations.RunPython(create_governance_triggers, drop_governance_triggers),
    ]
