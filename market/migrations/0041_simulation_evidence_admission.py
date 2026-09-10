"""Closed evidence admission for available simulations; no pricing formulas."""

import json

from django.db import migrations

FIELDS = {
    "cost": {
        "component": "text",
        "source": "text",
        "version": "text",
        "content_sha256": "hash",
        "quote_currency": "currency",
        "known_at": "time",
        "valid_from": "time",
        "valid_through": "time",
        "spread": "amount",
        "commission_per_side": "amount",
        "slippage_per_side": "amount",
        "financing_reserve": "amount",
        "latency_seconds": "integer",
    },
    "calendar": {
        "version": "text",
        "source_url": "text",
        "profile": "text",
        "known_at": "time",
        "open_intervals": "intervals",
        "closed_intervals": "intervals",
    },
    "terms": {
        "source_sha256": "hash",
        "base_currency": "currency",
        "quote_currency": "currency",
        "account_currency": "currency",
        "from_at": "time",
        "through_at": "time",
        "known_at": "time",
        "conversion_at": "time",
        "conversion_rate": "amount",
        "rollovers": "rollovers",
        "provenance": "text",
        "cost_unit": "text",
        "conversion_unit": "text",
    },
}

SQL = r"""
CREATE FUNCTION phase5_v3_evidence_value(v jsonb, kind text) RETURNS boolean LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE item jsonb; t text;
BEGIN
 IF kind IN ('intervals','rollovers') THEN
   IF jsonb_typeof(v) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
   FOR item IN SELECT value FROM jsonb_array_elements(v) LOOP
     IF jsonb_typeof(item) IS DISTINCT FROM 'array' OR jsonb_array_length(item)<>2
       OR phase5_v2_value(item->0,'time') IS NOT TRUE THEN RETURN false; END IF;
     IF kind='intervals' THEN
       IF phase5_v2_value(item->1,'time') IS NOT TRUE OR item->>0>=item->>1 THEN RETURN false; END IF;
     ELSIF phase5_v3_evidence_value(item->1,'signed_amount') IS NOT TRUE THEN RETURN false;
     END IF;
   END LOOP;
   RETURN true;
 END IF;
 IF kind='integer' THEN
   RETURN jsonb_typeof(v)='number' AND v::text ~ '^(0|[1-9][0-9]*)$';
 END IF;
 IF kind IN ('currency','amount','signed_amount') THEN
   IF jsonb_typeof(v) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
   t := v #>> '{}';
   IF kind='currency' THEN RETURN t IN ('USD','CAD','EUR','GBP','JPY','CHF','AUD','NZD','NOK','SEK'); END IF;
   -- Input evidence is lossless encoded(exact=True), not six-place output rounding.
   IF t !~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$' THEN RETURN false; END IF;
   RETURN kind='signed_amount' OR t::numeric>=0;
 END IF;
 RETURN phase5_v2_value(v,kind);
EXCEPTION WHEN OTHERS THEN RETURN false;
END; $$;

CREATE FUNCTION phase5_v3_evidence(v jsonb, kind text) RETURNS boolean LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE fields jsonb; k text; typ text; item jsonb;
BEGIN
 fields := '__FIELDS__'::jsonb->kind;
 IF fields IS NULL OR jsonb_typeof(v) IS DISTINCT FROM 'object' OR
   (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v) key) IS DISTINCT FROM
   (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(fields) key) THEN RETURN false; END IF;
 FOR k,typ IN SELECT key,value FROM jsonb_each_text(fields) LOOP
   IF phase5_v3_evidence_value(v->k,typ) IS NOT TRUE THEN RETURN false; END IF;
 END LOOP;
 IF kind='cost' THEN RETURN v->>'valid_from'<=v->>'valid_through'; END IF;
 IF kind='calendar' THEN RETURN v->>'source_url' LIKE 'https://%'; END IF;
 IF v->>'base_currency'=v->>'quote_currency'
   OR v->>'cost_unit'<>'quote_per_base' OR v->>'conversion_unit'<>'account_per_quote'
   OR NOT (v->>'from_at'<=v->>'conversion_at' AND v->>'conversion_at'<=v->>'through_at'
           AND v->>'known_at'<=v->>'conversion_at')
   OR (v->>'conversion_rate')::numeric<=0 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(v->'rollovers') LOOP
   IF item->>0<v->>'from_at' OR item->>0>v->>'through_at' THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END; $$;

CREATE FUNCTION phase5_v3_simulation_evidence() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.output->>'schema'='phase5/execution-v1' AND (
   phase5_v3_evidence(NEW.outcome_evidence->'cost','cost') IS NOT TRUE OR
   phase5_v3_evidence(NEW.outcome_evidence->'calendar','calendar') IS NOT TRUE OR
   phase5_v3_evidence(NEW.outcome_evidence->'terms','terms') IS NOT TRUE)
 THEN RAISE EXCEPTION 'phase5_available_evidence_shape' USING ERRCODE='23514'; END IF;
 -- Unavailable output's closed schema and null-evidence allowance remain in v2.
 RETURN NEW;
END; $$;
CREATE TRIGGER phase5_v3_evidence BEFORE INSERT ON market_strategysimulation
FOR EACH ROW EXECUTE FUNCTION phase5_v3_simulation_evidence();
""".replace("__FIELDS__", json.dumps(FIELDS))

REVERSE = """
DROP TRIGGER phase5_v3_evidence ON market_strategysimulation;
DROP FUNCTION phase5_v3_simulation_evidence();
DROP FUNCTION phase5_v3_evidence(jsonb,text);
DROP FUNCTION phase5_v3_evidence_value(jsonb,text);
"""


class Migration(migrations.Migration):
    dependencies = [("market", "0040_strategy_contract_corrections")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
