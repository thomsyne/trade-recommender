"""Versioned forward guards; no historical rows or migration bodies are changed."""

from importlib import import_module

from django.db import migrations

previous = import_module("market.migrations.0034_market_state_semantic_guards")
DESCRIPTOR_0100_SHA256 = "798c1f30f956e1b7f49a8a6ae8377ecc2629f391491c392d1d0b04ece56b8d49"
# Reuse only frozen historical SQL, never live implementation constants.
OLD_FUNCTIONS = previous.SQL[
    previous.SQL.index("CREATE FUNCTION market_state_definition_insert()") : previous.SQL.index(
        "CREATE TRIGGER market_state_definition_semantics"
    )
].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")
NEW_FUNCTIONS = OLD_FUNCTIONS.replace("0.9.0", "0.10.0").replace(
    previous.DESCRIPTOR_090_SHA256, DESCRIPTOR_0100_SHA256
)

SQL = r"""
CREATE FUNCTION market_state_record_digest_v2(model text, ident bigint) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tab text; stored jsonb; k text; fields text[];
BEGIN
  tab := CASE model
    WHEN 'research.macroobservation' THEN 'research_macroobservation'
    WHEN 'research.economicevent' THEN 'research_economicevent'
    WHEN 'research.rawretrieval' THEN 'research_rawretrieval'
    WHEN 'research.sourcepolicy' THEN 'research_sourcepolicy'
    WHEN 'research.macroseries' THEN 'research_macroseries'
    WHEN 'market.sourceregistry' THEN 'market_sourceregistry' END;
  IF tab IS NULL THEN RETURN NULL; END IF;
  EXECUTE format('SELECT to_jsonb(r) FROM public.%I r WHERE id=$1', tab) INTO stored USING ident;
  IF stored IS NULL THEN RETURN NULL; END IF;
  fields := CASE model
    WHEN 'research.sourcepolicy' THEN ARRAY['id','source_id','jurisdiction','currency']
    WHEN 'research.macroseries' THEN ARRAY['id','source_policy_id','code','indicator','unit','transformation']
    WHEN 'market.sourceregistry' THEN ARRAY['id'] END;
  IF fields IS NOT NULL THEN
    SELECT jsonb_object_agg(key,value) INTO stored FROM jsonb_each(stored) WHERE key=ANY(fields);
  END IF;
  FOREACH k IN ARRAY ARRAY['first_observed_at','available_at','vintage_at','fetched_at','created_at','event_at'] LOOP
    IF stored ? k AND stored->k <> 'null'::jsonb THEN
      stored := jsonb_set(stored, ARRAY[k], to_jsonb(to_char((stored->>k)::timestamptz AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00'));
    END IF;
  END LOOP;
  FOREACH k IN ARRAY ARRAY['value','actual','estimate','previous'] LOOP
    IF stored ? k AND stored->k <> 'null'::jsonb THEN
      stored := jsonb_set(stored, ARRAY[k], to_jsonb(((stored->>k)::numeric(24,8))::text));
    END IF;
  END LOOP;
  IF model='research.rawretrieval' THEN
    stored := jsonb_set(stored, '{body}', to_jsonb(encode(sha256(decode(substr(stored->>'body',3),'hex')),'hex')));
  END IF;
  RETURN market_state_digest(stored);
END;
$$;

CREATE FUNCTION market_state_evidence_insert_v2() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE grp jsonb; item jsonb; g text; latest market_candleobservation%ROWTYPE; claimed jsonb;
  retrieval_id bigint; series_id bigint; policy_id bigint; source_id bigint; series_policy bigint;
  models text[]; ids bigint[]; i integer; horizon interval; lookback integer;
BEGIN
  FOR grp IN SELECT value FROM jsonb_array_elements(NEW.evidence_manifest->'events')
    UNION ALL SELECT value FROM jsonb_each(NEW.evidence_manifest->'macro') LOOP
    FOR item IN SELECT value FROM jsonb_array_elements(grp) LOOP
      IF item->>'content_sha256' IS DISTINCT FROM market_state_record_digest_v2(item->>'model',(item->>'id')::bigint) THEN
        RAISE EXCEPTION 'market_state_research_content_mismatch' USING ERRCODE='23514';
      END IF;
    END LOOP;
    -- The entire ordered lineage must follow the immutable record's actual FKs.
    IF grp->0->>'model' NOT IN ('research.macroobservation','research.economicevent') THEN
      RAISE EXCEPTION 'market_state_research_lineage_mismatch' USING ERRCODE='23514';
    END IF;
    IF grp->0->>'model'='research.macroobservation' THEN
      SELECT m.retrieval_id,m.series_id INTO retrieval_id,series_id FROM research_macroobservation m WHERE m.id=(grp->0->>'id')::bigint;
    ELSE
      SELECT e.retrieval_id,e.series_id INTO retrieval_id,series_id FROM research_economicevent e WHERE e.id=(grp->0->>'id')::bigint;
    END IF;
    SELECT r.source_policy_id,p.source_id INTO policy_id,source_id FROM research_rawretrieval r
      JOIN research_sourcepolicy p ON p.id=r.source_policy_id WHERE r.id=retrieval_id;
    models := ARRAY[grp->0->>'model','research.rawretrieval','research.sourcepolicy','market.sourceregistry'];
    ids := ARRAY[(grp->0->>'id')::bigint,retrieval_id,policy_id,source_id];
    IF series_id IS NOT NULL THEN
      models := models || ARRAY['research.macroseries']; ids := ids || series_id;
      SELECT s.source_policy_id INTO series_policy FROM research_macroseries s WHERE s.id=series_id;
      IF series_policy<>policy_id THEN
        SELECT p.source_id INTO source_id FROM research_sourcepolicy p WHERE p.id=series_policy;
        models := models || ARRAY['research.sourcepolicy','market.sourceregistry'];
        ids := ids || ARRAY[series_policy,source_id];
      END IF;
    END IF;
    IF jsonb_array_length(grp)<>cardinality(ids) THEN
      RAISE EXCEPTION 'market_state_research_lineage_mismatch' USING ERRCODE='23514';
    END IF;
    FOR i IN 1..cardinality(ids) LOOP
      IF grp->(i-1)->>'model' IS DISTINCT FROM models[i] OR (grp->(i-1)->>'id')::bigint IS DISTINCT FROM ids[i] THEN
        RAISE EXCEPTION 'market_state_research_lineage_mismatch' USING ERRCODE='23514';
      END IF;
    END LOOP;
  END LOOP;
  FOR g IN SELECT value FROM jsonb_array_elements_text(NEW.output_payload->'requested_granularities')
    UNION SELECT unnest(ARRAY['M15','D','W']) LOOP
    lookback := CASE g WHEN 'M15' THEN 500 WHEN 'D' THEN 400 ELSE 300 END;
    horizon := CASE g WHEN 'M15' THEN interval '15 minutes' WHEN 'H1' THEN interval '1 hour'
      WHEN 'H4' THEN interval '4 hours' WHEN 'D' THEN interval '24 hours' ELSE interval '168 hours' END;
    SELECT * INTO latest FROM market_candleobservation c
      WHERE c.instrument_id=NEW.instrument_id AND c.granularity=g AND c.complete
        AND c.observed_at<=NEW.information_cutoff AND c.interval_end<=NEW.information_cutoff
        AND c.timestamp<NEW.information_cutoff AND c.content_sha256<>''
        AND c.timestamp>=NEW.information_cutoff-horizon*(3*lookback+14)
      ORDER BY c.timestamp DESC,c.revision DESC LIMIT 1;
    SELECT value INTO claimed FROM jsonb_array_elements(NEW.input_manifest)
      WHERE value->>'granularity'=g ORDER BY value->>'timestamp' DESC LIMIT 1;
    IF latest.id IS NOT NULL AND (
       (claimed->>'timestamp')::timestamptz IS DISTINCT FROM latest.timestamp
       OR (claimed->>'revision')::int IS DISTINCT FROM latest.revision) THEN
      RAISE EXCEPTION 'market_state_not_latest_manifest_candle' USING ERRCODE='23514';
    END IF;
    IF NOT (NEW.output_payload->'granularities') ? g THEN CONTINUE; END IF;
    claimed := NEW.output_payload->'granularities'->g->'latest_eligible_candle';
    IF latest.id IS NOT NULL AND (
       (claimed->>'timestamp')::timestamptz IS DISTINCT FROM latest.timestamp
       OR (claimed->>'revision')::int IS DISTINCT FROM latest.revision) THEN
      RAISE EXCEPTION 'market_state_not_latest_eligible_candle' USING ERRCODE='23514';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER market_state_z_evidence BEFORE INSERT ON market_marketstatesnapshot
FOR EACH ROW EXECUTE FUNCTION market_state_evidence_insert_v2();

CREATE FUNCTION market_instrument_currencies_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF NEW.code NOT IN ('AUD_USD','USD_CAD','GBP_USD','EUR_GBP','EUR_USD','USD_JPY',
      'USD_CHF','NZD_USD','EUR_JPY','GBP_JPY','AUD_JPY','AUD_CAD')
    OR NEW.base_currency<>split_part(NEW.code,'_',1) OR NEW.quote_currency<>split_part(NEW.code,'_',2)
  THEN RAISE EXCEPTION 'instrument_currency_contradiction' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER market_instrument_currencies BEFORE INSERT OR UPDATE ON market_instrument
FOR EACH ROW EXECUTE FUNCTION market_instrument_currencies_v1();

CREATE FUNCTION market_research_semantics_immutable_v1() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_TABLE_NAME='research_sourcepolicy' THEN
    IF ROW(OLD.source_id,OLD.jurisdiction,OLD.currency) IS DISTINCT FROM ROW(NEW.source_id,NEW.jurisdiction,NEW.currency)
      AND (EXISTS(SELECT 1 FROM research_rawretrieval WHERE source_policy_id=OLD.id)
        OR EXISTS(SELECT 1 FROM research_macroseries WHERE source_policy_id=OLD.id)) THEN
      RAISE EXCEPTION 'consumed_research_semantics_immutable' USING ERRCODE='23514';
    END IF;
  ELSE
    IF ROW(OLD.source_policy_id,OLD.code,OLD.indicator,OLD.unit,OLD.transformation)
      IS DISTINCT FROM ROW(NEW.source_policy_id,NEW.code,NEW.indicator,NEW.unit,NEW.transformation)
      AND (EXISTS(SELECT 1 FROM research_macroobservation WHERE series_id=OLD.id)
        OR EXISTS(SELECT 1 FROM research_economicevent WHERE series_id=OLD.id)) THEN
      RAISE EXCEPTION 'consumed_research_semantics_immutable' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER market_research_policy_semantics BEFORE UPDATE ON research_sourcepolicy
FOR EACH ROW EXECUTE FUNCTION market_research_semantics_immutable_v1();
CREATE TRIGGER market_research_series_semantics BEFORE UPDATE ON research_macroseries
FOR EACH ROW EXECUTE FUNCTION market_research_semantics_immutable_v1();
"""

REVERSE = """
DROP TRIGGER market_research_series_semantics ON research_macroseries;
DROP TRIGGER market_research_policy_semantics ON research_sourcepolicy;
DROP FUNCTION market_research_semantics_immutable_v1();
DROP TRIGGER market_instrument_currencies ON market_instrument;
DROP FUNCTION market_instrument_currencies_v1();
DROP TRIGGER market_state_z_evidence ON market_marketstatesnapshot;
DROP FUNCTION market_state_evidence_insert_v2();
DROP FUNCTION market_state_record_digest_v2(text,bigint);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0034_market_state_semantic_guards"),
        ("research", "0007_economicevent_series_economicevent_source_url_and_more"),
    ]
    operations = [migrations.RunSQL(NEW_FUNCTIONS + SQL, REVERSE + OLD_FUNCTIONS)]
