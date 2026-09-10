"""Prospective semantic guards; existing immutable evidence is never rewritten."""

from django.db import migrations

# This migration admits exactly the frozen 0.9.0 contract, not arbitrary future
# definitions. A regression compares this value with Python's canonical body.
# Future versions need a forward migration; never import mutable runtime code in
# a historical migration or silently update a previously installed contract.
DESCRIPTOR_090_SHA256 = "f8e52064d0bb1e6144bc3f889fcc473112a9e6a08a4da3763d5a3dcc0c0862c6"

SQL = r"""
CREATE FUNCTION market_state_canonical(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result text;
BEGIN
  CASE jsonb_typeof(value)
    WHEN 'object' THEN
      SELECT '{' || coalesce(string_agg(to_json(key)::text || ':' ||
        market_state_canonical(val), ',' ORDER BY key COLLATE "C"), '') || '}'
      INTO result FROM jsonb_each(value) AS e(key,val);
    WHEN 'array' THEN
      SELECT '[' || coalesce(string_agg(market_state_canonical(val), ',' ORDER BY n), '') || ']'
      INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS e(val,n);
    WHEN 'number' THEN
      IF value::text !~ '^-?[0-9]+$' THEN
        RAISE EXCEPTION 'market_state_noncanonical_number' USING ERRCODE='23514';
      END IF;
      result := value::text;
    ELSE result := value::text;
  END CASE;
  RETURN result;
END;
$$;

CREATE FUNCTION market_state_digest(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT encode(sha256(convert_to(market_state_canonical(value), 'UTF8')), 'hex')
$$;

CREATE FUNCTION market_state_terms_valid(value jsonb, registry jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE k text; v jsonb; allowed text[];
BEGIN
  IF jsonb_typeof(value)='object' THEN
    FOR k,v IN SELECT * FROM jsonb_each(value) LOOP
      IF k='version' AND (jsonb_typeof(v)<>'string' OR NOT registry ? (v #>> '{}')) THEN
        RETURN false;
      END IF;
      allowed := CASE k
        WHEN 'classification' THEN ARRAY['uptrend','downtrend','range']
        WHEN 'regime' THEN ARRAY['compression','normal','expansion']
        WHEN 'label' THEN ARRAY['first_high','first_low','equal_high','equal_low','higher_high','higher_low','lower_high','lower_low']
        WHEN 'kind' THEN ARRAY['high','low','demand_candidate','supply_candidate']
        WHEN 'direction' THEN ARRAY['up','down','bullish','bearish','tightening','easing','steady','unknown']
        WHEN 'side' THEN ARRAY['above','below','at']
        ELSE NULL END;
      IF allowed IS NOT NULL AND (jsonb_typeof(v)<>'string' OR NOT (v #>> '{}')=ANY(allowed)) THEN
        RETURN false;
      END IF;
      IF NOT market_state_terms_valid(v,registry) THEN RETURN false; END IF;
    END LOOP;
  ELSIF jsonb_typeof(value)='array' THEN
    FOR v IN SELECT * FROM jsonb_array_elements(value) LOOP
      IF NOT market_state_terms_valid(v,registry) THEN RETURN false; END IF;
    END LOOP;
  ELSIF jsonb_typeof(value)='string' AND (value #>> '{}')=ANY(ARRAY[
      'A+ setup','strong level','clear draw on liquidity','smart money entered',
      'institutional order block','session bias','obvious support','high-probability FVG']) THEN
    RETURN false;
  END IF;
  RETURN true;
END;
$$;

CREATE FUNCTION market_state_definition_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.key <> 'market-state-descriptor' OR NEW.version <> '0.9.0'
     OR NEW.definition_sha256 <> '__DESCRIPTOR_090_SHA256__'
     OR jsonb_typeof(NEW.definition->'algorithms') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.definition->'features') IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.definition->'thresholds') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.definition->'lookbacks') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.definition->'terminology') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.definition->'session_policy') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.definition->'context_policy') IS DISTINCT FROM 'object'
     OR NEW.definition->>'price_basis' IS DISTINCT FROM 'midpoint'
     OR NEW.definition->>'calendar_policy' IS DISTINCT FROM 'ny-fx-week-v1'
     OR NEW.definition->>'missing_data_policy' IS DISTINCT FROM 'explicit-unavailable-v1'
     OR NEW.definition->'rounding' IS DISTINCT FROM
          '{"quantum":"0.000001","mode":"ROUND_HALF_EVEN"}'::jsonb
     OR NEW.definition_sha256 <> market_state_digest(NEW.definition)
  THEN RAISE EXCEPTION 'market_state_invalid_definition' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION market_state_snapshot_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  d market_marketstatedefinition%ROWTYPE;
  instrument_code text;
  p jsonb := NEW.output_payload;
  scope jsonb;
  entry jsonb;
  stamp timestamptz;
  cutoff_text text;
  expected_scope jsonb;
  g text;
  block jsonb;
  n integer;
  group_value jsonb;
  record_value jsonb;
  table_name text;
  stored jsonb;
BEGIN
  SELECT * INTO STRICT d FROM market_marketstatedefinition WHERE id=NEW.definition_id;
  SELECT code INTO STRICT instrument_code FROM market_instrument WHERE id=NEW.instrument_id;
  IF d.key <> 'market-state-descriptor' OR d.version <> '0.9.0'
     OR d.definition_sha256 <> '__DESCRIPTOR_090_SHA256__'
     OR d.definition_sha256 <> market_state_digest(d.definition)
  THEN RAISE EXCEPTION 'market_state_invalid_definition' USING ERRCODE='23514'; END IF;
  cutoff_text := to_char(NEW.information_cutoff AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00';
  scope := p->'requested_granularities';
  IF jsonb_typeof(p) IS DISTINCT FROM 'object'
     OR p->>'schema' IS DISTINCT FROM 'market-state/descriptor-v0'
     OR p->'definition' IS DISTINCT FROM jsonb_build_array(d.key,d.version)
     OR p->>'instrument' IS DISTINCT FROM instrument_code
     OR p->>'information_cutoff' IS DISTINCT FROM cutoff_text
     OR jsonb_typeof(p->'granularities') IS DISTINCT FROM 'object'
     OR jsonb_typeof(scope) IS DISTINCT FROM 'array'
     OR jsonb_typeof(p->'prior_extremes') IS DISTINCT FROM 'object'
     OR jsonb_typeof(p->'monthly_context') IS DISTINCT FROM 'object'
     OR jsonb_typeof(p->'opening_range') IS DISTINCT FROM 'object'
     OR jsonb_typeof(p->'event_state') IS DISTINCT FROM 'object'
     OR jsonb_typeof(p->'macro_regime') IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'market_state_invalid_payload' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(p)) <> 11
     OR jsonb_typeof(NEW.evidence_manifest) IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.evidence_manifest->'events') IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.evidence_manifest->'macro') IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'market_state_invalid_payload' USING ERRCODE='23514'; END IF;
  IF NOT market_state_terms_valid(p,d.definition->'terminology') THEN
    RAISE EXCEPTION 'market_state_noncanonical_terminology' USING ERRCODE='23514';
  END IF;
  SELECT coalesce(jsonb_agg(key ORDER BY key COLLATE "C"),'[]'::jsonb)
    INTO expected_scope FROM jsonb_object_keys(p->'granularities') AS k(key);
  IF scope <> expected_scope OR jsonb_array_length(scope)=0
     OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(scope) AS requested(value)
               WHERE requested.value NOT IN ('M15','H1','H4','D','W'))
     OR NEW.output_sha256 <> market_state_digest(p)
     OR NEW.input_manifest_sha256 <> market_state_digest(NEW.input_manifest)
     OR NEW.idempotency_key <> market_state_digest(jsonb_build_array(
          d.definition_sha256, instrument_code, cutoff_text, scope,
          NEW.input_manifest_sha256, market_state_digest(NEW.evidence_manifest)))
  THEN RAISE EXCEPTION 'market_state_identity_mismatch' USING ERRCODE='23514'; END IF;
  IF jsonb_typeof(NEW.input_manifest) IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.input_manifest)>5000
  THEN RAISE EXCEPTION 'market_state_invalid_manifest' USING ERRCODE='23514'; END IF;
  FOR entry IN SELECT value FROM jsonb_array_elements(NEW.input_manifest) LOOP
    IF jsonb_typeof(entry) IS DISTINCT FROM 'object'
       OR entry->>'granularity' IS NULL
       OR entry->>'granularity' NOT IN ('M15','H1','H4','D','W')
       OR jsonb_typeof(entry->'revision') IS DISTINCT FROM 'number'
       OR coalesce(entry->>'revision','') !~ '^[1-9][0-9]{0,8}$'
       OR coalesce(entry->>'content_sha256','') !~ '^[0-9a-f]{64}$'
       OR coalesce(entry->>'timestamp','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$'
    THEN RAISE EXCEPTION 'market_state_invalid_manifest' USING ERRCODE='23514'; END IF;
    BEGIN stamp := (entry->>'timestamp')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
      RAISE EXCEPTION 'market_state_invalid_timestamp' USING ERRCODE='23514';
    END;
    IF NOT EXISTS(SELECT 1 FROM market_candleobservation c
       WHERE c.instrument_id=NEW.instrument_id AND c.granularity=entry->>'granularity'
         AND c.timestamp=stamp AND c.revision=(entry->>'revision')::int
         AND c.content_sha256=entry->>'content_sha256' AND c.complete
         AND c.interval_end<=NEW.information_cutoff AND c.observed_at<=NEW.information_cutoff)
    THEN RAISE EXCEPTION 'market_state_invalid_lineage' USING ERRCODE='23514'; END IF;
    IF EXISTS(SELECT 1 FROM market_candleobservation c
       WHERE c.instrument_id=NEW.instrument_id AND c.granularity=entry->>'granularity'
         AND c.timestamp=stamp AND c.revision>(entry->>'revision')::int
         AND c.complete AND c.interval_end<=NEW.information_cutoff
         AND c.observed_at<=NEW.information_cutoff)
    THEN RAISE EXCEPTION 'market_state_obsolete_revision' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF NEW.input_manifest IS DISTINCT FROM (
      SELECT coalesce(jsonb_agg(e ORDER BY e->>'granularity' COLLATE "C", e->>'timestamp'), '[]'::jsonb)
      FROM (SELECT DISTINCT value AS e FROM jsonb_array_elements(NEW.input_manifest)) AS entries)
  THEN RAISE EXCEPTION 'market_state_noncanonical_manifest' USING ERRCODE='23514'; END IF;
  FOR g,block IN SELECT * FROM jsonb_each(p->'granularities') LOOP
    SELECT count(*) INTO n FROM jsonb_array_elements(NEW.input_manifest) e WHERE e->>'granularity'=g;
    IF (n=0 AND block IS DISTINCT FROM '{"state":"unavailable","reason_code":"insufficient_history"}'::jsonb)
       OR (n>0 AND (block->>'state' IS DISTINCT FROM 'available'
           OR block->'eligible_candle_count' IS DISTINCT FROM to_jsonb(n)
           OR jsonb_typeof(block->'higher_timeframe') IS DISTINCT FROM 'object'
           OR jsonb_typeof(block->'structure') IS DISTINCT FROM 'object'
           OR jsonb_typeof(block->'liquidity') IS DISTINCT FROM 'object'
           OR jsonb_typeof(block->'fvg') IS DISTINCT FROM 'object'
           OR jsonb_typeof(block->'spread') IS DISTINCT FROM 'object'))
    THEN RAISE EXCEPTION 'market_state_invalid_prerequisites' USING ERRCODE='23514'; END IF;
    IF n>0 AND NOT EXISTS (
      SELECT 1 FROM market_candleobservation c
      WHERE c.instrument_id=NEW.instrument_id AND c.granularity=g
        AND c.timestamp=(block->'latest_eligible_candle'->>'timestamp')::timestamptz
        AND to_jsonb(c.revision)=block->'latest_eligible_candle'->'revision'
        AND round((c.bid_close+c.ask_close)/2,6)
            - CASE WHEN mod(abs(c.bid_close+c.ask_close)*500000,2)=0.5
                THEN sign(c.bid_close+c.ask_close)*0.000001 ELSE 0 END
            =(block->'latest_eligible_candle'->>'midpoint_close')::numeric
        AND c.observed_at<=NEW.information_cutoff AND c.interval_end<=NEW.information_cutoff
    ) THEN RAISE EXCEPTION 'market_state_invalid_latest_candle' USING ERRCODE='23514'; END IF;
  END LOOP;
  IF jsonb_array_length(NEW.evidence_manifest->'events')>2048
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.evidence_manifest->'macro'))>2048
  THEN RAISE EXCEPTION 'market_state_invalid_research_lineage' USING ERRCODE='23514'; END IF;
  FOR group_value IN
      SELECT value FROM jsonb_array_elements(NEW.evidence_manifest->'events')
      UNION ALL SELECT value FROM jsonb_each(NEW.evidence_manifest->'macro')
  LOOP
    IF jsonb_typeof(group_value) IS DISTINCT FROM 'array' OR jsonb_array_length(group_value)>20
    THEN RAISE EXCEPTION 'market_state_invalid_research_lineage' USING ERRCODE='23514'; END IF;
    FOR record_value IN SELECT value FROM jsonb_array_elements(group_value) LOOP
      table_name := CASE record_value->>'model'
        WHEN 'research.economicevent' THEN 'research_economicevent'
        WHEN 'research.macroobservation' THEN 'research_macroobservation'
        WHEN 'research.rawretrieval' THEN 'research_rawretrieval'
        WHEN 'research.sourcepolicy' THEN 'research_sourcepolicy'
        WHEN 'research.macroseries' THEN 'research_macroseries'
        WHEN 'market.sourceregistry' THEN 'market_sourceregistry' ELSE NULL END;
      IF table_name IS NULL OR coalesce(record_value->>'id','') !~ '^[1-9][0-9]{0,17}$'
         OR coalesce(record_value->>'content_sha256','') !~ '^[0-9a-f]{64}$'
      THEN RAISE EXCEPTION 'market_state_invalid_research_lineage' USING ERRCODE='23514'; END IF;
      EXECUTE format('SELECT to_jsonb(r) FROM public.%I r WHERE id=$1',table_name)
        INTO stored USING (record_value->>'id')::bigint;
      IF stored IS NULL THEN
        RAISE EXCEPTION 'market_state_invalid_research_lineage' USING ERRCODE='23514';
      END IF;
      FOREACH g IN ARRAY ARRAY['first_observed_at','available_at','vintage_at','fetched_at'] LOOP
        IF (stored->>g)::timestamptz>NEW.information_cutoff THEN
          RAISE EXCEPTION 'market_state_research_after_cutoff' USING ERRCODE='23514';
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
  RETURN NEW;
END;
$$;

CREATE TRIGGER market_state_definition_semantics BEFORE INSERT ON market_marketstatedefinition
FOR EACH ROW EXECUTE FUNCTION market_state_definition_insert();
CREATE TRIGGER market_state_snapshot_semantics BEFORE INSERT ON market_marketstatesnapshot
FOR EACH ROW EXECUTE FUNCTION market_state_snapshot_insert();

ALTER FUNCTION market_state_canonical(jsonb) SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION market_state_digest(jsonb) SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION market_state_terms_valid(jsonb,jsonb) SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION market_state_definition_insert() SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION market_state_snapshot_insert() SET search_path = pg_catalog, public, pg_temp;
""".replace("__DESCRIPTOR_090_SHA256__", DESCRIPTOR_090_SHA256)

REVERSE_SQL = """
DROP TRIGGER market_state_snapshot_semantics ON market_marketstatesnapshot;
DROP TRIGGER market_state_definition_semantics ON market_marketstatedefinition;
DROP FUNCTION market_state_snapshot_insert();
DROP FUNCTION market_state_definition_insert();
DROP FUNCTION market_state_terms_valid(jsonb,jsonb);
DROP FUNCTION market_state_digest(jsonb);
DROP FUNCTION market_state_canonical(jsonb);
"""


class Migration(migrations.Migration):
    dependencies = [("market", "0033_market_state_integrity_constraints")]
    operations = [migrations.RunSQL(SQL, REVERSE_SQL)]
