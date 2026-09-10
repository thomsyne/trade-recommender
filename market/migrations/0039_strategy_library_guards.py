"""Frozen prospective contracts; Python owns formulas, SQL owns durable identities."""

import json

from django.db import migrations

PINS = {
    "ewmac-d-v1": "16ca050cb431264990d34fe2bee537846d16e0a67da95c7bd13dec263f9ed452",
    "breakout-d-v1": "6ce253071f1530f77c3e42239f84238ab0fad13547f084ff98012cd5accb4c1c",
    "fast-mr-h1-v1": "ec2690048339a393980188f25bfc13a0bc26af7871087409d61bb84c5ba0e567",
    "pullback-m15-v1": "ce503915c9e893958fce7a9651942c982a3935d0c17372a989ce26cf271bc4d8",
    "pullback-h1-v1": "c3e68729a72bb38c965c3b8eefdfef4a3eb6e16c1cfe6a7f48d2e21fc8b2b1fd",
    "range-m15-v1": "24ec48ec20a876ed873d4b1785871533b5e5be5678750a7500842d51aebf0093",
    "phase5-sweep-reversal-v1": "b49bb0138434a92beddcf24a7e1e5f1fc415f4dd3e8ae8de234d9341990bb1e8",
    "phase5-acceptance-continuation-v1": "fa98b1f6874e24da73641d6c010b938cb951a2630980d64d5b308ea29b5adf6d",
    "carry-readiness-v1": "55fdd73813fb384b304a5afff44cb71d5ab8a445191383e46403dae19ffa459c",
    "macro-risk-v1": "4b75fff84e9889ba2ae27acc784205b4c8151d95f7939a89cc20d0f2f7dcf112",
    "fixed-risk-v1": "323a0d1573578dc689ed668ca9cf57f627c31ba8277a6433add9ccb17b7fb386",
    "ewma-risk-v1": "3f926cd1ab99984abbbd7a744bf017a47c6ab7342d217028a2bb374044fe2977",
    "garch-t-risk-v1": "5bd22aee240f0b24748f6361b7d6be1e388683ff47725907357686a22229cefa",
    "orb-m15-wick-v1:london": "526623c867ed0753cb88d6c6c2dafd76e658d354b9b1f52c950ce7ac12bc90cd",
    "orb-m15-wick-v1:new_york": "5db3a9ca12320d5d5beaacc03c8495b209965d9a9fa900392f75cb04f8208bbd",
    "orb-m15-confirmed-v1:london": "c5e6ed32a8d8564a863441d8442c11a6f7c87f3b49f53b65195917e9bc689f98",
    "orb-m15-confirmed-v1:new_york": "914921e84d8d9bf785d3aa06f77814ebb9778045cc50e73363a9328e26e2bc92",
    "orb-m15-fvg-v1:london": "a1f10c9c7e8396c283f2c6d15c63a40508a5561300bb992b1139953c48f8b6ed",
    "orb-m15-fvg-v1:new_york": "aa2fd61acde2a7dfd6cca1a3023ce3d79bea0ee5ed53b64deb454eb2fe8c6018",
}

SQL = r"""
CREATE FUNCTION phase5_definition_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.body_sha256 IS DISTINCT FROM market_state_digest(NEW.body)
 OR NEW.body_sha256 IS DISTINCT FROM ('__PINS__'::jsonb->>NEW.strategy)
 OR NEW.body->>'strategy' IS DISTINCT FROM NEW.strategy THEN
   RAISE EXCEPTION 'phase5_definition_contract' USING ERRCODE='23514';
 END IF;
 NEW.registered_at := clock_timestamp();
 RETURN NEW;
END; $$;

CREATE FUNCTION phase5_evaluation_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE d market_strategydefinition; s market_marketstatesnapshot; p market_strategyevaluation;
        ps market_marketstatesnapshot; part jsonb; kind text;
BEGIN
 SELECT * INTO STRICT d FROM market_strategydefinition WHERE id=NEW.definition_id;
 SELECT * INTO STRICT s FROM market_marketstatesnapshot WHERE id=NEW.snapshot_id;
 IF s.information_cutoff >= '2027-01-01T00:00:00Z'::timestamptz AND d.registered_at >= '2027-01-01T00:00:00Z'::timestamptz THEN
   RAISE EXCEPTION 'phase5_holdout_not_preregistered' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM market_marketstatedefinition WHERE id=s.definition_id AND definition_sha256='9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3')
 OR NEW.evidence_sha256 IS DISTINCT FROM market_state_digest(NEW.evidence)
 OR NEW.output_sha256 IS DISTINCT FROM market_state_digest(NEW.output)
 OR NEW.identity IS DISTINCT FROM market_state_digest(jsonb_build_array(d.body_sha256,NEW.snapshot_id,NEW.evidence_sha256))
 OR NEW.evidence->>'snapshot_key' IS DISTINCT FROM s.idempotency_key
 OR NEW.evidence->'previous_id' IS DISTINCT FROM coalesce(to_jsonb(NEW.previous_id),'null'::jsonb)
 OR jsonb_typeof(NEW.evidence->'costs') IS DISTINCT FROM 'array'
 OR NEW.output->>'strategy' IS DISTINCT FROM d.strategy
 OR NEW.output->>'schema' IS DISTINCT FROM 'phase5/evaluation-v1'
 OR NEW.output->>'activation' IS DISTINCT FROM 'forbidden'
 OR jsonb_typeof(NEW.output->'outputs') IS DISTINCT FROM 'array'
 OR jsonb_array_length(NEW.output->'outputs') NOT BETWEEN 1 AND 3
 THEN RAISE EXCEPTION 'phase5_evaluation_contract' USING ERRCODE='23514'; END IF;
 IF NEW.previous_id IS NOT NULL THEN
   SELECT * INTO STRICT p FROM market_strategyevaluation WHERE id=NEW.previous_id;
   SELECT * INTO STRICT ps FROM market_marketstatesnapshot WHERE id=p.snapshot_id;
   IF p.definition_id<>NEW.definition_id OR ps.instrument_id<>s.instrument_id OR ps.information_cutoff>=s.information_cutoff
   THEN RAISE EXCEPTION 'phase5_previous_attribution' USING ERRCODE='23514'; END IF;
 END IF;
 FOR part IN SELECT value FROM jsonb_array_elements(NEW.output->'outputs') LOOP
   kind := part->>'schema';
   IF part->>'strategy' IS DISTINCT FROM d.strategy OR kind IS NULL OR kind NOT IN
      ('phase5/unavailable-v1','phase5/continuous-v1','phase5/setup-v1','phase5/risk-v1')
   THEN RAISE EXCEPTION 'phase5_output_kind' USING ERRCODE='23514'; END IF;
   IF kind='phase5/unavailable-v1' AND (part->>'reason' IS NULL OR part ?| ARRAY['direction','value','multiplier'])
   THEN RAISE EXCEPTION 'phase5_unknown_not_neutral' USING ERRCODE='23514'; END IF;
   IF kind='phase5/risk-v1' AND (NOT part ? 'multiplier' OR part ?| ARRAY['direction','target','stop'] OR
      (part->>'multiplier' IS NOT NULL AND ((part->>'multiplier')::numeric NOT BETWEEN 0 AND 1)))
   THEN RAISE EXCEPTION 'phase5_risk_bounds' USING ERRCODE='23514'; END IF;
   IF kind='phase5/continuous-v1' AND (part ?| ARRAY['direction','target','stop'] OR
      NOT part ?& ARRAY['value','buffered','reason','components'] OR
      ((part->>'value' IS NULL) <> (part->>'reason' IS NOT NULL)) OR
      (part->>'value' IS NOT NULL AND (part->>'value')::numeric NOT BETWEEN -20 AND 20) OR
      (part->>'buffered' IS NOT NULL AND (part->>'buffered')::numeric NOT BETWEEN -20 AND 20))
   THEN RAISE EXCEPTION 'phase5_continuous_bounds' USING ERRCODE='23514'; END IF;
   IF kind='phase5/setup-v1' AND (NOT jsonb_strip_nulls(part) ?& ARRAY['direction','available_at','signal_start','entry_at','expires_at','exit_at','reference','stop','target','granularity','evidence'] OR
      part->>'direction' NOT IN ('-1','1') OR part->>'granularity' NOT IN ('M15','H1') OR
      (part->>'available_at')::timestamptz>s.information_cutoff OR
      (part->>'signal_start')::timestamptz>=(part->>'available_at')::timestamptz OR
      (part->>'entry_at')::timestamptz<(part->>'available_at')::timestamptz OR
      (part->>'entry_at')::timestamptz<s.information_cutoff OR
      (part->>'entry_at')::timestamptz>(part->>'expires_at')::timestamptz OR
      (part->>'expires_at')::timestamptz>=(part->>'exit_at')::timestamptz)
   THEN RAISE EXCEPTION 'phase5_setup_chronology' USING ERRCODE='23514'; END IF;
 END LOOP;
 NEW.created_at := clock_timestamp();
 RETURN NEW;
END; $$;

CREATE FUNCTION phase5_simulation_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE e market_strategyevaluation; s market_marketstatesnapshot; o market_marketstatesnapshot;
        d market_strategydefinition; candidate jsonb; period text;
BEGIN
 SELECT * INTO STRICT e FROM market_strategyevaluation WHERE id=NEW.evaluation_id;
 SELECT * INTO STRICT s FROM market_marketstatesnapshot WHERE id=e.snapshot_id;
 SELECT * INTO STRICT o FROM market_marketstatesnapshot WHERE id=NEW.outcome_snapshot_id;
 SELECT * INTO STRICT d FROM market_strategydefinition WHERE id=e.definition_id;
 SELECT p INTO STRICT candidate FROM jsonb_array_elements(e.output->'outputs') p WHERE p->>'schema'='phase5/setup-v1';
 period := candidate->>'signal_start';
 IF d.strategy LIKE 'orb-%' THEN
   period := to_char((period::timestamptz AT TIME ZONE (CASE WHEN d.strategy LIKE '%:london' THEN 'Europe/London' ELSE 'America/New_York' END)), 'YYYY-MM-DD');
 END IF;
 IF s.instrument_id<>o.instrument_id OR o.information_cutoff<=s.information_cutoff
 OR NEW.outcome_evidence->>'outcome_snapshot_key' IS DISTINCT FROM o.idempotency_key
 OR NEW.outcome_evidence->>'outcome_snapshot_id' IS DISTINCT FROM NEW.outcome_snapshot_id::text
 OR NEW.attempt_key IS DISTINCT FROM market_state_digest(jsonb_build_array(e.definition_id,s.instrument_id,period))
 OR NEW.intent->>'schema' IS DISTINCT FROM 'phase5/intent-v1'
 OR NEW.intent->>'candidate_sha256' IS DISTINCT FROM market_state_digest(candidate)
 OR NEW.intent->>'simulator_sha256' IS DISTINCT FROM market_state_digest(d.body->'simulator')
 OR NEW.intent->>'cost_sha256' IS DISTINCT FROM market_state_digest(NEW.outcome_evidence->'cost')
 OR NEW.intent->>'calendar_sha256' IS DISTINCT FROM market_state_digest(NEW.outcome_evidence->'calendar')
 OR coalesce(NEW.output->>'schema','') NOT IN ('phase5/execution-v1','phase5/unavailable-v1')
 OR (NEW.output->>'schema'='phase5/execution-v1' AND NEW.output->>'intent_sha256' IS DISTINCT FROM market_state_digest(NEW.intent))
 OR NEW.output_sha256 IS DISTINCT FROM market_state_digest(NEW.output)
 OR NEW.identity IS DISTINCT FROM market_state_digest(jsonb_build_array(NEW.evaluation_id,NEW.intent,NEW.outcome_evidence))
 THEN RAISE EXCEPTION 'phase5_simulation_contract' USING ERRCODE='23514'; END IF;
 NEW.created_at := clock_timestamp();
 RETURN NEW;
END; $$;

CREATE FUNCTION phase5_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'phase5 immutable evidence' USING ERRCODE='23514'; END; $$;
""".replace("__PINS__", json.dumps(PINS))

TABLES = ("strategydefinition", "strategyevaluation", "strategysimulation")
SQL += "\n".join(
    f"""
CREATE TRIGGER phase5_immutable BEFORE UPDATE OR DELETE ON market_{table}
FOR EACH ROW EXECUTE FUNCTION phase5_reject_mutation();
CREATE TRIGGER phase5_no_truncate BEFORE TRUNCATE ON market_{table}
FOR EACH STATEMENT EXECUTE FUNCTION market_state_reject_truncate();
CREATE TRIGGER phase5_validate BEFORE INSERT ON market_{table}
FOR EACH ROW EXECUTE FUNCTION phase5_{name}_insert();
"""
    for table, name in zip(TABLES, ("definition", "evaluation", "simulation"))
)

REVERSE = "\n".join(
    f"""
DROP TRIGGER phase5_validate ON market_{table};
DROP TRIGGER phase5_no_truncate ON market_{table};
DROP TRIGGER phase5_immutable ON market_{table};
"""
    for table in TABLES
) + "\n".join(
    f"DROP FUNCTION phase5_{name}();"
    for name in ("definition_insert", "evaluation_insert", "simulation_insert", "reject_mutation")
)


def refuse_populated_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE market_strategydefinition,market_strategyevaluation,market_strategysimulation IN ACCESS EXCLUSIVE MODE"
        )
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM market_strategydefinition) OR EXISTS(SELECT 1 FROM market_strategyevaluation) OR EXISTS(SELECT 1 FROM market_strategysimulation)"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("phase5_populated_reverse_refused")


class Migration(migrations.Migration):
    dependencies = [("market", "0038_strategy_library_records")]
    operations = [
        migrations.RunSQL(SQL, REVERSE),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
