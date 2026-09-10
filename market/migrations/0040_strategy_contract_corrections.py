"""Forward-only closed output admission; existing immutable evidence is untouched."""

import json
from importlib import import_module

from django.db import migrations

PREVIOUS = import_module("market.migrations.0039_strategy_library_guards")
# Frozen at correction completion, never imported from live strategy code.
PINS = {
    "ewmac-d-v1": "60fb6331e52a4b5355778575012e4de2cc92f14f0369e918c15f811a9f847cd6",
    "breakout-d-v1": "33403b41e3f13ec511e81500887125e8de46f805d96e63f5ab51bb568eb49ebf",
    "fast-mr-h1-v1": "bad4db4a4f9be70e95b2b7fa21854f50b37024e15a9071ac3bdb62b7ab5036af",
    "pullback-m15-v1": "731727b8c979a9db6189c8802b61ce56749a5c8d18b34b97e6fe78c57f1efd66",
    "pullback-h1-v1": "1e1c635e4e70c8b08d19bb09200ec34398edcc0ccd648454c541a16134f28cfb",
    "range-m15-v1": "4e36e299d4c489eb9459c25d2b8c9f3801029a791a3e2c94b1733c68a437bd7d",
    "phase5-sweep-reversal-v1": "01a18f20cdc70b292324ae5f5b074fa06d73caf94b828639f65b4dc69b983f0f",
    "phase5-acceptance-continuation-v1": "58451829bec046fdc7f18b04550038c0c3e69fa39df6a99dad1ae93d72ae7412",
    "carry-readiness-v1": "f84acfdda89a23dde8dbbf8c3279ce07dd54c559cbdf304df4d78d45188d83b4",
    "macro-risk-v1": "70a18b770221a43928d54f086aa9b94dfc17219adbb7610b80b0ecf3d506a33e",
    "fixed-risk-v1": "7ad2158179479ae60b8df75d468e14c596e90e311903e3cefdfa7c17dc569889",
    "ewma-risk-v1": "57bde853cd606416e8b2600cb05860396bceb2a2e965d651d1be5d3e6b427253",
    "garch-t-risk-v1": "fefaefcca9cd7250cca5486e25c163e5a0965bcf1ce221979e14f4c1da38eb51",
    "orb-m15-wick-v1:london": "99e9612237a34da82cab0e1594277f344b9cf438b1c59ce2b7c30e052c2b9213",
    "orb-m15-wick-v1:new_york": "5f7dac9e55fb9063cdfd33eef22bfa2903e9cd359824fc9f4a5da95b8e22c36f",
    "orb-m15-confirmed-v1:london": "10eb3ca7218216918c2d06f18a49f48a0097107c0431c9f0dca1ecb3bc74c28b",
    "orb-m15-confirmed-v1:new_york": "88991a3320dcde47c4fbed2184833ec162ff5f2a94fe76514820b2f1a0ddb01a",
    "orb-m15-fvg-v1:london": "37ca6e0b5fe3df76b577306d59316544559b18c5ac50e43999f1d44728f8fe59",
    "orb-m15-fvg-v1:new_york": "643f518287b874f15ff5c148ce03ec0f613af93aa76431bc94e5ea0691a61d25",
}
FIELDS = {
    "unavailable": {"strategy": "text", "reason": "text"},
    "risk": {"strategy": "text", "multiplier": "decimal?", "reason": "text", "evidence": "texts"},
    "continuous": {
        "strategy": "text",
        "value": "decimal?",
        "buffered": "decimal?",
        "reason": "text?",
        "components": "components",
    },
    "setup": {
        "strategy": "text",
        "direction": "direction",
        "available_at": "time",
        "signal_start": "time",
        "granularity": "granularity",
        "reference": "decimal",
        "stop": "decimal",
        "target": "decimal",
        "entry_at": "time",
        "expires_at": "time",
        "exit_at": "time",
        "evidence": "texts",
    },
    "intent": {
        "candidate_sha256": "hash",
        "simulator_sha256": "hash",
        "cost_sha256": "hash",
        "calendar_sha256": "hash",
    },
    "execution": {
        "intent_sha256": "hash",
        "entered_at": "time",
        "exited_at": "time",
        "entry": "decimal",
        "exit": "decimal",
        "gross_quote": "decimal",
        "costs_quote": "decimal",
        "net_quote": "decimal",
        "net_account": "decimal",
        "outcome_evidence": "hashes",
        "reason": "text",
    },
}
COMPONENT = {"name": "text", "raw": "decimal?", "capped": "decimal?", "exclusion": "text?"}

SQL = r"""
CREATE FUNCTION phase5_v2_value(v jsonb, kind text) RETURNS boolean LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE item jsonb; t text;
BEGIN
 IF right(kind,1)='?' THEN RETURN v='null'::jsonb OR phase5_v2_value(v,left(kind,-1)); END IF;
 IF kind IN ('texts','hashes','components') THEN
   IF jsonb_typeof(v) IS DISTINCT FROM 'array' OR jsonb_array_length(v)>1801 THEN RETURN false; END IF;
   FOR item IN SELECT value FROM jsonb_array_elements(v) LOOP
     IF kind='components' THEN
       IF NOT phase5_v2_object(item,'__COMPONENT__'::jsonb) THEN RETURN false; END IF;
       IF ((item->>'raw' IS NULL)<>(item->>'capped' IS NULL)) OR
          (item->>'raw' IS NULL AND item->>'exclusion' IS NULL) OR abs((item->>'capped')::numeric)>20 THEN RETURN false; END IF;
     ELSIF NOT phase5_v2_value(item,CASE WHEN kind='texts' THEN 'text' ELSE 'hash' END) THEN RETURN false;
     END IF;
   END LOOP;
   RETURN true;
 END IF;
 IF kind='direction' THEN RETURN jsonb_typeof(v)='number' AND v::text IN ('-1','1'); END IF;
 IF jsonb_typeof(v) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
 t := v #>> '{}';
 -- Match Python str.strip's Unicode whitespace set, independent of DB locale.
 IF kind='text' THEN RETURN length(btrim(t,U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'))>0; END IF;
 IF kind='hash' THEN RETURN t ~ '^[0-9a-f]{64}$'; END IF;
 IF kind='decimal' THEN RETURN t ~ '^-?(0|[1-9][0-9]{0,26})\.[0-9]{6}$'; END IF;
 IF kind='granularity' THEN RETURN t IN ('M15','H1'); END IF;
 IF kind='time' THEN
   IF t !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00$' THEN RETURN false; END IF;
   RETURN to_char(t::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00' = t;
 END IF;
 RETURN false;
EXCEPTION WHEN OTHERS THEN RETURN false;
END; $$;

CREATE FUNCTION phase5_v2_object(v jsonb, fields jsonb) RETURNS boolean LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k text; kind text;
BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'object' OR
    (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(v) key) IS DISTINCT FROM
    (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(fields) key) THEN RETURN false; END IF;
 FOR k,kind IN SELECT key,value FROM jsonb_each_text(fields) LOOP
   IF phase5_v2_value(v->k,kind) IS NOT TRUE THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END; $$;

CREATE FUNCTION phase5_v2_part(p jsonb, kind text) RETURNS boolean LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE fields jsonb;
BEGIN
 fields := '__FIELDS__'::jsonb->kind;
 IF fields IS NULL OR NOT phase5_v2_object(p,fields || '{"schema":"text"}'::jsonb)
    OR p->>'schema' IS DISTINCT FROM 'phase5/'||kind||'-v1' THEN RETURN false; END IF;
 IF kind='continuous' AND (((p->>'value' IS NULL)<>(p->>'buffered' IS NULL)) OR
    ((p->>'value' IS NULL)<>(p->>'reason' IS NOT NULL)) OR
    abs((p->>'value')::numeric)>20 OR abs((p->>'buffered')::numeric)>20) THEN RETURN false; END IF;
 IF kind='risk' AND (p->>'multiplier')::numeric NOT BETWEEN 0 AND 1 THEN RETURN false; END IF;
 IF kind='setup' AND (NOT (p->>'signal_start'<p->>'available_at' AND p->>'available_at'<=p->>'entry_at'
    AND p->>'entry_at'<=p->>'expires_at' AND p->>'expires_at'<p->>'exit_at') OR
    least((p->>'reference')::numeric,(p->>'stop')::numeric,(p->>'target')::numeric)<=0 OR
    (p->>'direction')::int*((p->>'reference')::numeric-(p->>'stop')::numeric)<=0 OR
    (p->>'direction')::int*((p->>'target')::numeric-(p->>'reference')::numeric)<=0) THEN RETURN false; END IF;
 IF kind='execution' AND (p->>'entered_at'>=p->>'exited_at' OR jsonb_array_length(p->'outcome_evidence')=0 OR
    least((p->>'entry')::numeric,(p->>'exit')::numeric)<=0) THEN RETURN false; END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END; $$;

CREATE FUNCTION phase5_v2_evaluation() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE strategy text; kinds text[]; p jsonb; kind text; valid boolean;
BEGIN
 SELECT d.strategy INTO STRICT strategy FROM market_strategydefinition d WHERE id=NEW.definition_id;
 IF jsonb_typeof(NEW.output) IS DISTINCT FROM 'object' OR
    (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.output) key) IS DISTINCT FROM
    ARRAY['activation','outputs','schema','strategy']::text[] OR jsonb_typeof(NEW.output->'outputs') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'phase5_evaluation_shape' USING ERRCODE='23514'; END IF;
 kinds := ARRAY(SELECT replace(replace(value->>'schema','phase5/',''),'-v1','') FROM jsonb_array_elements(NEW.output->'outputs'));
 valid := CASE
 WHEN strategy IN ('ewmac-d-v1','breakout-d-v1') THEN kinds=ARRAY['continuous']
 WHEN strategy='fast-mr-h1-v1' THEN cardinality(kinds) IN (2,3) AND kinds[1] IN ('setup','unavailable') AND kinds[2]='risk' AND (cardinality(kinds)=2 OR kinds[3]='continuous')
 WHEN strategy='macro-risk-v1' THEN kinds=ARRAY['risk','unavailable']
 WHEN strategy='carry-readiness-v1' THEN kinds=ARRAY['unavailable']
 WHEN strategy IN ('fixed-risk-v1','ewma-risk-v1','garch-t-risk-v1') THEN kinds=ARRAY['risk']
 ELSE '__PINS__'::jsonb ? strategy AND cardinality(kinds)=1 AND kinds[1] IN ('setup','unavailable') END;
 IF valid IS NOT TRUE THEN RAISE EXCEPTION 'phase5_strategy_output_kind' USING ERRCODE='23514'; END IF;
 FOR p IN SELECT value FROM jsonb_array_elements(NEW.output->'outputs') LOOP
   kind := replace(replace(p->>'schema','phase5/',''),'-v1','');
   IF phase5_v2_part(p,kind) IS NOT TRUE OR p->>'strategy' IS DISTINCT FROM strategy
   THEN RAISE EXCEPTION 'phase5_output_shape' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NEW;
END; $$;

CREATE FUNCTION phase5_v2_simulation() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE strategy text; kind text; candidate jsonb; cutoff timestamptz;
BEGIN
 SELECT d.strategy,p,s.information_cutoff INTO STRICT strategy,candidate,cutoff
 FROM market_strategyevaluation e JOIN market_strategydefinition d ON d.id=e.definition_id
 CROSS JOIN LATERAL jsonb_array_elements(e.output->'outputs') p
 JOIN market_marketstatesnapshot s ON s.id=NEW.outcome_snapshot_id
 WHERE e.id=NEW.evaluation_id AND p->>'schema'='phase5/setup-v1';
 kind := CASE NEW.output->>'schema' WHEN 'phase5/execution-v1' THEN 'execution' WHEN 'phase5/unavailable-v1' THEN 'unavailable' ELSE '' END;
 IF NOT phase5_v2_part(NEW.intent,'intent') OR NOT phase5_v2_part(NEW.output,kind)
 OR (kind='unavailable' AND NEW.output->>'strategy' IS DISTINCT FROM strategy)
 OR (kind='execution' AND ((NEW.output->>'entered_at')::timestamptz<(candidate->>'entry_at')::timestamptz
     OR (NEW.output->>'entered_at')::timestamptz>(candidate->>'expires_at')::timestamptz
     OR (NEW.output->>'exited_at')::timestamptz>cutoff))
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.outcome_evidence) key) IS DISTINCT FROM
    ARRAY['calendar','cost','outcome_snapshot_id','outcome_snapshot_key','profile','terms']::text[]
 OR jsonb_typeof(NEW.outcome_evidence->'outcome_snapshot_id') IS DISTINCT FROM 'number'
 OR NEW.outcome_evidence->>'outcome_snapshot_id' !~ '^[1-9][0-9]*$'
 OR NOT phase5_v2_value(NEW.outcome_evidence->'outcome_snapshot_key','hash')
 OR NOT phase5_v2_value(NEW.outcome_evidence->'profile','text')
 THEN RAISE EXCEPTION 'phase5_simulation_shape' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER phase5_v2_shape BEFORE INSERT ON market_strategyevaluation FOR EACH ROW EXECUTE FUNCTION phase5_v2_evaluation();
CREATE TRIGGER phase5_v2_shape BEFORE INSERT ON market_strategysimulation FOR EACH ROW EXECUTE FUNCTION phase5_v2_simulation();
"""
SQL = (
    SQL.replace("__FIELDS__", json.dumps(FIELDS))
    .replace("__COMPONENT__", json.dumps(COMPONENT))
    .replace("__PINS__", json.dumps(PINS))
)
DEFINITION_SQL = (
    PREVIOUS.SQL.split("CREATE FUNCTION phase5_evaluation_insert()")[0]
    .replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")
    .replace(json.dumps(PREVIOUS.PINS), json.dumps(PINS))
)
REVERSE = """
DROP TRIGGER phase5_v2_shape ON market_strategyevaluation;
DROP TRIGGER phase5_v2_shape ON market_strategysimulation;
DROP FUNCTION phase5_v2_simulation(); DROP FUNCTION phase5_v2_evaluation();
DROP FUNCTION phase5_v2_part(jsonb,text); DROP FUNCTION phase5_v2_object(jsonb,jsonb);
DROP FUNCTION phase5_v2_value(jsonb,text);
""" + PREVIOUS.SQL.split("CREATE FUNCTION phase5_evaluation_insert()")[0].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"
)


class Migration(migrations.Migration):
    dependencies = [("market", "0039_strategy_library_guards")]
    operations = [
        migrations.RunSQL(SQL + DEFINITION_SQL, REVERSE),
        migrations.RunPython(migrations.RunPython.noop, PREVIOUS.refuse_populated_reverse),
    ]
