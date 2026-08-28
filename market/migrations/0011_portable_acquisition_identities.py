from importlib import import_module

from django.db import migrations


def require_empty_phase2b(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM market_historicaldatasetplan)
               OR EXISTS(SELECT 1 FROM market_historicalingestionchunk)
               OR EXISTS(SELECT 1 FROM market_historicalingestionattempt)
               OR EXISTS(SELECT 1 FROM market_datasetregistration)
               OR EXISTS(SELECT 1 FROM market_datasetversion WHERE manifest ? 'historical_plan_sha256')
               OR EXISTS(SELECT 1 FROM market_auditevent
                    WHERE event_type LIKE 'market.historical_attempt_%%')"""
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "Phase 2B.1 identity correction requires an empty historical evidence set"
            )


def apply_correction(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION market_validate_historical_plan() RETURNS trigger AS $$
        DECLARE strategy record; parameter record; source record; expected_payload jsonb;
                item record;
        BEGIN
          SELECT v.*,d.key AS definition_key INTO STRICT strategy
            FROM research_strategyversion v JOIN research_strategydefinition d ON d.id=v.definition_id
            WHERE v.id=NEW.strategy_version_id;
          SELECT * INTO STRICT parameter FROM research_strategyparametermanifest
            WHERE strategy_version_id=NEW.strategy_version_id;
          SELECT * INTO STRICT source FROM market_sourceregistry WHERE id=NEW.source_id;
          expected_payload := jsonb_build_object(
            'acquisition_contract','failed-break-historical-acquisition',
            'acquisition_version','phase-2b1-v1',
            'source',jsonb_build_object('name',source.name,
              'governed_identity','oanda-v20-market-candles-v1'),
            'strategy',jsonb_build_object('definition_key',strategy.definition_key,
              'version',strategy.version,'content_hash',strategy.content_hash),
            'data_identity',strategy.data_identity,'dataset',NEW.payload->'dataset',
            'instruments',NEW.instruments,'granularities',NEW.granularities,
            'ranges',NEW.ranges,'alignment',NEW.alignment,
            'price_component',NEW.price_component,'complete_only',NEW.complete_only,
            'chunk_size',NEW.chunk_size,'phase1_spec_hash',NEW.phase1_spec_hash,
            'phase1_manifest_hash',NEW.phase1_manifest_hash);
          IF NEW.instruments <> '["AUD_USD","EUR_GBP","EUR_USD","GBP_USD","USD_CAD","USD_JPY"]'::jsonb
             OR NEW.granularities <> '["D","H1","W"]'::jsonb
             OR NEW.alignment <> '{"timezone":"America/New_York","daily_hour":17,"weekly_day":"Friday","smooth":false}'::jsonb
             OR NEW.price_component <> 'COMBINED_BID_ASK' OR NOT NEW.complete_only
             OR NEW.phase1_spec_hash <> '47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash <> 'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR source.name<>'OANDA v20' OR source.tier<>'established' OR NOT source.enabled
             OR source.acquisition_method<>'v20 REST API' OR source.llm_processing_allowed
             OR strategy.content_hash<>NEW.phase1_manifest_hash
             OR strategy.data_identity<>NEW.identity
             OR strategy.pair_metadata<>'{"instruments":["EUR_USD","GBP_USD","EUR_GBP","USD_CAD","USD_JPY","AUD_USD"]}'::jsonb
             OR parameter.sha256<>strategy.content_hash
             OR parameter.phase1_spec_hash<>NEW.phase1_spec_hash
             OR parameter.phase1_manifest_hash<>NEW.phase1_manifest_hash
             OR jsonb_typeof(NEW.payload->'dataset')<>'object'
             OR (SELECT count(*) FROM jsonb_object_keys(NEW.payload->'dataset'))<>3
             OR NOT (NEW.payload->'dataset' ?& array['name','version','description'])
             OR NEW.payload<>expected_payload OR NEW.sha256<>market_sha256(expected_payload)
             OR NOT NEW.ranges ?& array['D','H1','W'] THEN
            RAISE EXCEPTION 'historical plan conflicts with the portable canonical contract';
          END IF;
          FOR item IN SELECT * FROM jsonb_each(NEW.ranges) LOOP
            IF item.key NOT IN ('D','H1','W')
               OR item.value <> (CASE item.key
                    WHEN 'D' THEN '{"from":"2009-02-26T22:00:00+00:00",
                      "to":"2018-12-31T22:00:00+00:00",
                      "expected_count_per_instrument":2567}'::jsonb
                    WHEN 'H1' THEN '{"from":"2009-12-31T15:00:00+00:00",
                      "to":"2019-01-01T04:00:00+00:00",
                      "expected_count_per_instrument":56341}'::jsonb
                    WHEN 'W' THEN '{"from":"2009-12-18T22:00:00+00:00",
                      "to":"2018-12-28T22:00:00+00:00",
                      "expected_count_per_instrument":471}'::jsonb
                  END)
            THEN RAISE EXCEPTION 'historical plan range is not the frozen calendar range'; END IF;
          END LOOP;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE FUNCTION market_validate_historical_dataset() RETURNS trigger AS $$
        DECLARE plan record; strategy record; expected_manifest jsonb; required_ranges jsonb;
        BEGIN
          IF TG_OP='DELETE' THEN
            IF OLD.manifest ? 'historical_plan_sha256' THEN
              RAISE EXCEPTION 'historical dataset manifests are immutable';
            END IF;
            RAISE EXCEPTION 'market_datasetversion is append-only';
          END IF;
          IF TG_OP='UPDATE' THEN
            IF OLD.manifest ? 'historical_plan_sha256'
               OR NEW.manifest ? 'historical_plan_sha256' THEN
              RAISE EXCEPTION 'historical dataset manifests are immutable';
            END IF;
            RAISE EXCEPTION 'market_datasetversion is append-only';
          END IF;
          IF NOT NEW.manifest ? 'historical_plan_sha256' THEN RETURN NEW; END IF;
          SELECT * INTO STRICT plan FROM market_historicaldatasetplan
            WHERE sha256=NEW.manifest->>'historical_plan_sha256';
          SELECT * INTO STRICT strategy FROM research_strategyversion
            WHERE id=plan.strategy_version_id;
          SELECT jsonb_agg(jsonb_build_object(
                   'instrument',instrument.value,
                   'granularity',granularity.value,
                   'start',plan.ranges->granularity.value->'from',
                   'end',plan.ranges->granularity.value->'to')
                   ORDER BY instrument.ordinality,granularity.ordinality)
            INTO required_ranges
            FROM jsonb_array_elements_text(plan.instruments)
                   WITH ORDINALITY AS instrument(value,ordinality)
            CROSS JOIN jsonb_array_elements_text(plan.granularities)
                   WITH ORDINALITY AS granularity(value,ordinality);
          expected_manifest := jsonb_build_object(
            'strategy_manifest_sha256',strategy.content_hash,
            'partition',jsonb_build_object('name','development','start_year',2010,'end_year',2018),
            'required_ranges',required_ranges,
            'historical_plan_sha256',plan.sha256,
            'price_component',plan.price_component,
            'complete_only',plan.complete_only,
            'instruments',plan.instruments,
            'granularities',plan.granularities,
            'alignment',plan.alignment);
          IF NEW.source_id<>plan.source_id OR NEW.name<>plan.payload->'dataset'->>'name'
             OR NEW.version<>plan.payload->'dataset'->>'version'
             OR NEW.description<>plan.payload->'dataset'->>'description'
             OR NEW.manifest<>expected_manifest
             OR NEW.manifest_sha256<>market_sha256(expected_manifest)
          THEN RAISE EXCEPTION 'historical dataset conflicts with portable plan identity'; END IF;
          RETURN NEW;
        EXCEPTION WHEN NO_DATA_FOUND THEN
          RAISE EXCEPTION 'historical dataset lacks its canonical plan';
        END $$ LANGUAGE plpgsql;
        DROP TRIGGER market_datasetversion_append_only ON market_datasetversion;
        DROP FUNCTION market_datasetversion_reject_mutation();
        CREATE TRIGGER market_historical_dataset_validate BEFORE INSERT OR UPDATE OR DELETE
          ON market_datasetversion
          FOR EACH ROW EXECUTE FUNCTION market_validate_historical_dataset();

        CREATE OR REPLACE FUNCTION market_validate_historical_chunk() RETURNS trigger AS $$
        DECLARE plan record; dataset record; instrument_code text; expected jsonb;
                request_hash text; expected_key text;
        BEGIN
          SELECT * INTO STRICT plan FROM market_historicaldatasetplan WHERE id=NEW.plan_id;
          SELECT * INTO STRICT dataset FROM market_datasetversion WHERE id=NEW.dataset_version_id;
          SELECT code INTO STRICT instrument_code FROM market_instrument WHERE id=NEW.instrument_id;
          expected := jsonb_build_object('instrument',instrument_code,'granularity',NEW.granularity,
            'from',to_char(NEW.requested_from AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00',
            'to',to_char(NEW.requested_to AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00',
            'price','BA','price_component','COMBINED_BID_ASK','smooth',false,
            'dailyAlignment',17,'alignmentTimezone','America/New_York',
            'weeklyAlignment','Friday','includeFirst',true,'complete_only',true);
          request_hash := market_sha256(expected);
          expected_key := market_sha256(jsonb_build_object('plan_sha256',plan.sha256,
            'dataset_manifest_sha256',dataset.manifest_sha256,
            'canonical_request_sha256',request_hash));
          IF dataset.manifest->>'historical_plan_sha256' IS DISTINCT FROM plan.sha256
             OR dataset.source_id<>plan.source_id
             OR dataset.name<>plan.payload->'dataset'->>'name'
             OR dataset.version<>plan.payload->'dataset'->>'version'
             OR NOT plan.instruments @> to_jsonb(instrument_code)
             OR NOT plan.granularities @> to_jsonb(NEW.granularity)
             OR NEW.canonical_request<>expected OR NEW.canonical_request_sha256<>request_hash
             OR NEW.logical_key<>expected_key OR NEW.requested_from>=NEW.requested_to
             OR market_expected_count(NEW.requested_from,NEW.requested_to,NEW.granularity)
                NOT BETWEEN 1 AND 4999
             OR NEW.requested_to>=timestamptz '2019-01-01 05:00:00+00'
             OR NEW.requested_from<(plan.ranges->NEW.granularity->>'from')::timestamptz
             OR NEW.requested_to>(plan.ranges->NEW.granularity->>'to')::timestamptz
             OR EXISTS (SELECT 1 FROM market_datasetregistration
                         WHERE dataset_version_id=NEW.dataset_version_id)
          THEN RAISE EXCEPTION 'historical chunk conflicts with canonical plan lineage'; END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION market_historical_manifest_valid(
          manifest_payload jsonb, manifest_dataset_id bigint, manifest_run_id bigint
        ) RETURNS boolean AS $$
        DECLARE lineage record; request_item jsonb; environment text; expected_evidence jsonb;
        BEGIN
          SELECT a.attempt_number,a.idempotency_key,c.logical_key,c.dataset_version_id,
                 c.instrument_id,c.granularity,c.requested_from,c.requested_to,
                 c.canonical_request,c.canonical_request_sha256,p.source_id,i.code,
                 r.dataset_version_id AS run_dataset_id,r.source_id AS run_source_id,
                 r.instrument_id AS run_instrument_id,r.granularity AS run_granularity,
                 r.requested_from AS run_from,r.requested_to AS run_to,r.parameters,
                 r.request_manifest_hash INTO STRICT lineage
            FROM market_historicalingestionattempt a
            JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
            JOIN market_historicaldatasetplan p ON p.id=c.plan_id
            JOIN market_instrument i ON i.id=c.instrument_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE a.ingestion_run_id=manifest_run_id;
          IF jsonb_typeof(manifest_payload)<>'object'
             OR jsonb_typeof(manifest_payload->'requests')<>'array'
             OR jsonb_array_length(manifest_payload->'requests')<>1
          THEN RETURN false; END IF;
          request_item := manifest_payload->'requests'->0;
          environment := request_item->>'oanda_environment';
          expected_evidence := jsonb_build_object(
            'endpoint_identity','oanda-v20-'||environment||':GET:/v3/instruments/'||
              lineage.code||'/candles','http_method','GET','oanda_environment',environment,
            'canonical_request_sha256',lineage.canonical_request_sha256,
            'provider_request_id',request_item->>'provider_request_id','http_status',200);
          RETURN coalesce(lineage.dataset_version_id=manifest_dataset_id
             AND lineage.run_dataset_id=manifest_dataset_id
             AND lineage.run_source_id=lineage.source_id
             AND lineage.run_instrument_id=lineage.instrument_id
             AND lineage.run_granularity=lineage.granularity
             AND lineage.run_from=lineage.requested_from AND lineage.run_to=lineage.requested_to
             AND lineage.parameters=lineage.canonical_request
             AND lineage.request_manifest_hash=market_sha256(
                   jsonb_build_object('attempt',lineage.idempotency_key))
             AND manifest_payload->'instrument'=to_jsonb(lineage.code)
             AND manifest_payload->'granularity'=to_jsonb(lineage.granularity)
             AND (manifest_payload->>'from')::timestamptz=lineage.requested_from
             AND (manifest_payload->>'to')::timestamptz=lineage.requested_to
             AND manifest_payload->'price'='"BA"'::jsonb
             AND manifest_payload->'price_component'='"COMBINED_BID_ASK"'::jsonb
             AND manifest_payload->'smooth'='false'::jsonb
             AND manifest_payload->'dailyAlignment'='17'::jsonb
             AND manifest_payload->'alignmentTimezone'='"America/New_York"'::jsonb
             AND manifest_payload->'weeklyAlignment'='"Friday"'::jsonb
             AND manifest_payload->'includeFirst'='true'::jsonb
             AND manifest_payload->'complete_only'='true'::jsonb
             AND manifest_payload->'historical_logical_key'=to_jsonb(lineage.logical_key)
             AND manifest_payload->'historical_attempt'=to_jsonb(lineage.attempt_number)
             AND environment IN ('practice','live')
             AND length(btrim(request_item->>'provider_request_id'))>0
             AND request_item=expected_evidence, false);
        EXCEPTION WHEN OTHERS THEN RETURN false;
        END $$ LANGUAGE plpgsql STABLE;
        """
    )


def reverse_correction(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    require_empty_phase2b(apps, schema_editor)
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS market_historical_dataset_validate ON market_datasetversion;"
        "DROP FUNCTION IF EXISTS market_validate_historical_dataset();"
        "CREATE FUNCTION market_datasetversion_reject_mutation() RETURNS trigger AS $$"
        "BEGIN RAISE EXCEPTION 'market_datasetversion is append-only'; END;"
        "$$ LANGUAGE plpgsql;"
        "CREATE TRIGGER market_datasetversion_append_only BEFORE UPDATE OR DELETE "
        "ON market_datasetversion FOR EACH ROW "
        "EXECUTE FUNCTION market_datasetversion_reject_mutation();"
    )
    migration_0010 = import_module("market.migrations.0010_dataset_registration_enforcement")
    migration_0010.drop_governance_triggers(apps, schema_editor)
    migration_0010.create_governance_triggers(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("market", "0010_dataset_registration_enforcement")]
    operations = [
        migrations.RunPython(require_empty_phase2b, migrations.RunPython.noop),
        migrations.RunPython(apply_correction, reverse_correction),
    ]
