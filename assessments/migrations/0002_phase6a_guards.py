"""Closed SQL admission, immutable ledgers, and safe populated reversal."""

from django.db import migrations

METHOD_DIGEST = "67b492068602ce4c9df380de98939c57d6abaef0cc1279468d9642ac377676f1"

SQL = r"""
CREATE FUNCTION phase6a_hash(v text) RETURNS boolean LANGUAGE sql IMMUTABLE
SET search_path=pg_catalog,public,pg_temp AS $$ SELECT v ~ '^[0-9a-f]{64}$' $$;

CREATE FUNCTION phase6a_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'phase6a immutable ledger' USING ERRCODE='23514'; END; $$;

CREATE FUNCTION phase6a_method_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.key IS DISTINCT FROM 'deterministic-multi-timeframe-assessment'
 OR NEW.version IS DISTINCT FROM '1.0.0'
 OR NEW.digest IS DISTINCT FROM '__METHOD__'
 OR NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/method-v1'
 OR NEW.payload->>'activation' IS DISTINCT FROM 'forbidden'
 THEN RAISE EXCEPTION 'phase6a_method_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at := clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_eligibility_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE code text; entry jsonb; expected_role text; found_count int;
BEGIN
 SELECT i.code INTO STRICT code FROM market_instrument i WHERE i.id=NEW.instrument_id;
 IF NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/eligibility-v1'
 OR NEW.payload->>'instrument' IS DISTINCT FROM code
 OR jsonb_typeof(NEW.payload->'entries') IS DISTINCT FROM 'array'
 OR NOT phase6a_hash(NEW.payload->>'phase55_decision_sha256')
 OR NOT phase6a_hash(NEW.payload->>'phase55_manifest_sha256')
 OR NOT phase6a_hash(NEW.payload->>'admission_provenance_sha256')
 OR coalesce(NEW.payload->>'era','')=''
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.payload) key) IS DISTINCT FROM
    ARRAY['admission_provenance_sha256','entries','era','instrument','phase55_decision_sha256','phase55_manifest_sha256','schema']::text[]
 THEN RAISE EXCEPTION 'phase6a_eligibility_contract' USING ERRCODE='23514'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(NEW.payload->'entries') LOOP
   expected_role := CASE
     WHEN entry->>'strategy' IN ('ewmac-d-v1','breakout-d-v1') THEN 'continuous_forecast'
     WHEN entry->>'strategy'='carry-readiness-v1' THEN 'readiness'
     WHEN entry->>'strategy' IN ('macro-risk-v1','fixed-risk-v1','ewma-risk-v1','garch-t-risk-v1') THEN 'overlay'
     ELSE 'setup' END;
   SELECT count(*) INTO found_count FROM market_strategydefinition d
    WHERE d.strategy=entry->>'strategy' AND d.body_sha256=entry->>'definition_sha256';
   IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(entry) key) IS DISTINCT FROM
      ARRAY['definition_sha256','required_evidence_ids','role','strategy']::text[]
   OR entry->>'role' IS DISTINCT FROM expected_role OR found_count<>1
   OR jsonb_typeof(entry->'required_evidence_ids') IS DISTINCT FROM 'array'
   OR jsonb_array_length(entry->'required_evidence_ids')<>0
   OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(entry->'required_evidence_ids') r WHERE NOT phase6a_hash(r))
   THEN RAISE EXCEPTION 'phase6a_eligibility_attribution' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM jsonb_array_elements(NEW.payload->'entries')) IS DISTINCT FROM
    (SELECT count(DISTINCT e->>'strategy') FROM jsonb_array_elements(NEW.payload->'entries') e)
 THEN RAISE EXCEPTION 'phase6a_duplicate_eligibility' USING ERRCODE='23514'; END IF;
 NEW.recorded_at := clock_timestamp(); NEW.valid_from := NEW.recorded_at;
 IF NEW.decision_known_at>NEW.recorded_at OR
    (NEW.valid_until IS NOT NULL AND NEW.valid_until<=NEW.valid_from)
 THEN RAISE EXCEPTION 'phase6a_eligibility_chronology' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_cost_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE code text; k text; v jsonb;
BEGIN
 SELECT i.code INTO STRICT code FROM market_instrument i WHERE i.id=NEW.instrument_id;
 IF NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/cost-evidence-v1'
 OR NEW.payload->>'known_at' IS DISTINCT FROM to_char(NEW.known_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'
 OR NEW.payload->>'stale_after' IS DISTINCT FROM to_char(NEW.stale_after AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'
 OR NEW.stale_after<=NEW.known_at
 OR NEW.payload->>'timestamp_precision' NOT IN ('microsecond','provider_exact')
 OR coalesce(NEW.payload->>'source_identity','')='' OR coalesce(NEW.payload->>'source_version','')=''
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.payload) key) IS DISTINCT FROM
    ARRAY['components','known_at','schema','source_identity','source_version','stale_after','timestamp_precision']::text[]
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.payload->'components') key) IS DISTINCT FROM
    ARRAY['commission','financing','slippage_latency','spread']::text[]
 THEN RAISE EXCEPTION 'phase6a_cost_contract' USING ERRCODE='23514'; END IF;
 FOR k,v IN SELECT key,value FROM jsonb_each(NEW.payload->'components') LOOP
   IF v<>'null'::jsonb AND (jsonb_typeof(v)<>'string' OR (v#>>'{}') !~ '^-?(0|[1-9][0-9]{0,26})\.[0-9]+$'
      OR (k<>'financing' AND (v#>>'{}')::numeric<0))
   THEN RAISE EXCEPTION 'phase6a_cost_value' USING ERRCODE='23514'; END IF;
 END LOOP;
 NEW.recorded_at := clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_capacity_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE currencies text[]; leg jsonb; seen text[]:=ARRAY[]::text[];
BEGIN
 SELECT string_to_array(i.code,'_') INTO STRICT currencies FROM market_instrument i WHERE i.id=NEW.instrument_id;
 IF NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/capacity-v1'
 OR NEW.payload->>'assessed_at' IS DISTINCT FROM to_char(NEW.assessed_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'
 OR NEW.payload->>'aggregate' NOT IN ('available','exceeded')
 OR coalesce(NEW.payload->>'policy_identity','')='' OR coalesce(NEW.payload->>'source_identity','')=''
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.payload) key) IS DISTINCT FROM
    ARRAY['aggregate','assessed_at','currency_legs','policy_identity','schema','source_identity']::text[]
 OR jsonb_array_length(NEW.payload->'currency_legs')<>2
 THEN RAISE EXCEPTION 'phase6a_capacity_contract' USING ERRCODE='23514'; END IF;
 FOR leg IN SELECT value FROM jsonb_array_elements(NEW.payload->'currency_legs') LOOP
   IF leg->>'currency'<>currencies[cardinality(seen)+1]
   OR leg->>'direction' NOT IN ('long','short') OR leg->>'disposition' NOT IN ('available','exceeded')
   OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(leg) key) IS DISTINCT FROM
      ARRAY['currency','direction','disposition']::text[]
   THEN RAISE EXCEPTION 'phase6a_capacity_legs' USING ERRCODE='23514'; END IF;
   seen:=array_append(seen,leg->>'currency');
 END LOOP;
 NEW.recorded_at := clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_assessment_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE s market_marketstatesnapshot; e assessments_eligibilitysnapshot;
        c assessments_costevidence; cap assessments_capacityassessment; item jsonb;
        reason text; states text[]:=ARRAY['available','unavailable','closed'];
BEGIN
 SELECT * INTO STRICT s FROM market_marketstatesnapshot WHERE id=NEW.snapshot_id;
 SELECT * INTO STRICT e FROM assessments_eligibilitysnapshot WHERE id=NEW.eligibility_id;
 IF NEW.information_cutoff<>s.information_cutoff OR e.instrument_id<>s.instrument_id
 OR e.valid_from>NEW.information_cutoff OR e.decision_known_at>NEW.information_cutoff
 OR e.recorded_at>NEW.information_cutoff OR (e.valid_until IS NOT NULL AND NEW.information_cutoff>=e.valid_until)
 OR NEW.input_digest IS DISTINCT FROM market_state_digest(NEW.input_manifest)
 OR NEW.output_digest IS DISTINCT FROM market_state_digest(NEW.output)
 OR NEW.input_manifest->>'method' IS DISTINCT FROM (SELECT digest FROM assessments_assessmentmethod WHERE id=NEW.method_id)
 OR NEW.input_manifest->'snapshot'->>'id' IS DISTINCT FROM NEW.snapshot_id::text
 OR NEW.input_manifest->'snapshot'->>'identity' IS DISTINCT FROM s.idempotency_key
 OR NEW.input_manifest->>'eligibility' IS DISTINCT FROM e.digest
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.input_manifest) key) IS DISTINCT FROM
    ARRAY['capacity','cost','eligibility','evaluations','evidence','method','schema','snapshot']::text[]
 OR NEW.input_manifest->>'schema' IS DISTINCT FROM 'phase6a/input-manifest-v1'
 OR jsonb_typeof(NEW.input_manifest->'evaluations') IS DISTINCT FROM 'array'
 OR NEW.input_manifest->'cost' IS DISTINCT FROM coalesce(to_jsonb((SELECT digest FROM assessments_costevidence WHERE id=NEW.cost_id)),'null'::jsonb)
 OR NEW.input_manifest->'capacity' IS DISTINCT FROM coalesce(to_jsonb((SELECT digest FROM assessments_capacityassessment WHERE id=NEW.capacity_id)),'null'::jsonb)
 OR NEW.input_manifest->'evidence' IS DISTINCT FROM coalesce(to_jsonb((SELECT digest FROM research_frozenevidencepacket WHERE id=NEW.evidence_packet_id)),'null'::jsonb)
 OR NEW.output->>'schema' IS DISTINCT FROM 'phase6a/assessment-v1'
 OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.output) key) IS DISTINCT FROM
    ARRAY['capacity','decision','directional_triggers','eligible_strategies','htf_regime','information_cutoff','major_zones','mechanical_trigger','reward_and_cost','schema','status','terminal_state']::text[]
 OR NEW.output->>'information_cutoff' IS DISTINCT FROM to_char(NEW.information_cutoff AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'
 THEN RAISE EXCEPTION 'phase6a_assessment_contract' USING ERRCODE='23514'; END IF;
 IF NEW.cost_id IS NOT NULL THEN SELECT * INTO STRICT c FROM assessments_costevidence WHERE id=NEW.cost_id;
   IF c.instrument_id<>s.instrument_id OR NEW.input_manifest->>'cost'<>c.digest OR c.known_at>NEW.information_cutoff
   THEN RAISE EXCEPTION 'phase6a_cost_provenance' USING ERRCODE='23514'; END IF; END IF;
 IF NEW.capacity_id IS NOT NULL THEN SELECT * INTO STRICT cap FROM assessments_capacityassessment WHERE id=NEW.capacity_id;
   IF cap.instrument_id<>s.instrument_id OR NEW.input_manifest->>'capacity'<>cap.digest OR cap.assessed_at>NEW.information_cutoff
   THEN RAISE EXCEPTION 'phase6a_capacity_provenance' USING ERRCODE='23514'; END IF; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.input_manifest->'evaluations') LOOP
   IF NOT EXISTS(SELECT 1 FROM market_strategyevaluation ev WHERE ev.id=(item->>'id')::bigint
     AND ev.snapshot_id=NEW.snapshot_id AND ev.identity=item->>'identity' AND ev.output_sha256=item->>'output_sha256')
   THEN RAISE EXCEPTION 'phase6a_evaluation_provenance' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOREACH reason IN ARRAY ARRAY['htf_regime','major_zones','eligible_strategies','directional_triggers','mechanical_trigger','reward_and_cost','capacity','terminal_state'] LOOP
   IF NOT (NEW.output->reason->>'state'=ANY(states)) THEN RAISE EXCEPTION 'phase6a_output_state' USING ERRCODE='23514'; END IF;
 END LOOP;
 reason:=NEW.output->'decision'->>'primary_reason';
 IF NOT (NEW.output->'decision'->>'state'=ANY(states))
 OR (reason IS NOT NULL AND reason NOT IN (__REASONS__))
 OR jsonb_typeof(NEW.output->'decision'->'gates')<>'array'
 THEN RAISE EXCEPTION 'phase6a_decision_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_candidate_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a assessments_multitimeframeassessment; ev market_strategyevaluation;
BEGIN
 SELECT * INTO STRICT a FROM assessments_multitimeframeassessment WHERE id=NEW.assessment_id;
 SELECT * INTO STRICT ev FROM market_strategyevaluation WHERE id=NEW.evaluation_id;
 IF a.output->>'status'<>'available' OR ev.snapshot_id<>a.snapshot_id
 OR NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.semantic_identity IS DISTINCT FROM NEW.payload->>'semantic_identity'
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/eligible-trade-intent-candidate-v1'
 OR NEW.payload->>'authority' IS DISTINCT FROM 'research_candidate_only_no_execution_or_trade_permission'
 OR NEW.payload->>'evaluation_identity' IS DISTINCT FROM ev.identity
 OR NEW.payload ?| ARRAY['order','fill','recommendation','size','execution','permission_to_trade']
 THEN RAISE EXCEPTION 'phase6a_candidate_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_supersession_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p assessments_eligibletradeintentcandidate; s assessments_eligibletradeintentcandidate;
BEGIN
 SELECT * INTO STRICT p FROM assessments_eligibletradeintentcandidate WHERE id=NEW.predecessor_id;
 SELECT * INTO STRICT s FROM assessments_eligibletradeintentcandidate WHERE id=NEW.successor_id;
 IF p.id=s.id OR s.predecessor_id<>p.id OR p.semantic_identity=s.semantic_identity
 OR NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema'<>'phase6a/intent-supersession-v1'
 OR NEW.payload->>'predecessor'<>p.digest OR NEW.payload->>'successor'<>s.digest
 THEN RAISE EXCEPTION 'phase6a_supersession_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;

CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_assessmentmethod FOR EACH ROW EXECUTE FUNCTION phase6a_method_insert();
CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_eligibilitysnapshot FOR EACH ROW EXECUTE FUNCTION phase6a_eligibility_insert();
CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_costevidence FOR EACH ROW EXECUTE FUNCTION phase6a_cost_insert();
CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_capacityassessment FOR EACH ROW EXECUTE FUNCTION phase6a_capacity_insert();
CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_multitimeframeassessment FOR EACH ROW EXECUTE FUNCTION phase6a_assessment_insert();
CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_eligibletradeintentcandidate FOR EACH ROW EXECUTE FUNCTION phase6a_candidate_insert();
CREATE TRIGGER phase6a_validate BEFORE INSERT ON assessments_intentsupersession FOR EACH ROW EXECUTE FUNCTION phase6a_supersession_insert();
__IMMUTABILITY__
"""

TABLES = (
    "assessmentmethod",
    "eligibilitysnapshot",
    "costevidence",
    "capacityassessment",
    "multitimeframeassessment",
    "eligibletradeintentcandidate",
    "intentsupersession",
)
REASONS = (
    "input_integrity_failure",
    "no_economically_admitted_strategy",
    "strategy_not_admitted_for_instrument",
    "strategy_role_cannot_originate_intent",
    "required_timeframe_unavailable",
    "m15_confirmation_unavailable",
    "technical_setup_absent",
    "trigger_pending",
    "trigger_rejected",
    "trigger_invalidated",
    "trigger_expired",
    "required_evidence_not_ready",
    "event_state_unknown",
    "event_window_blocked",
    "spread_unknown",
    "spread_exceeds_strategy_limit",
    "cost_evidence_missing",
    "cost_evidence_stale",
    "net_reward_nonpositive",
    "capacity_assessment_missing",
    "aggregate_capacity_exceeded",
    "currency_direction_capacity_exceeded",
    "conflicting_eligible_setups",
    "unchanged_duplicate_intent",
    "unsupported_intent_shape",
)
IMMUTABILITY = "\n".join(
    f"""CREATE TRIGGER phase6a_immutable BEFORE UPDATE OR DELETE ON assessments_{table}
FOR EACH ROW EXECUTE FUNCTION phase6a_reject_mutation();
CREATE TRIGGER phase6a_no_truncate BEFORE TRUNCATE ON assessments_{table}
FOR EACH STATEMENT EXECUTE FUNCTION market_state_reject_truncate();"""
    for table in TABLES
)
SQL = (
    SQL.replace("__METHOD__", METHOD_DIGEST)
    .replace("__REASONS__", ",".join(f"'{reason}'" for reason in REASONS))
    .replace("__IMMUTABILITY__", IMMUTABILITY)
)

REVERSE = (
    "\n".join(
        f"""DROP TRIGGER phase6a_no_truncate ON assessments_{table};
DROP TRIGGER phase6a_immutable ON assessments_{table};
DROP TRIGGER phase6a_validate ON assessments_{table};"""
        for table in TABLES
    )
    + "\n"
    + "\n".join(
        f"DROP FUNCTION phase6a_{name}();"
        for name in (
            "supersession_insert",
            "candidate_insert",
            "assessment_insert",
            "capacity_insert",
            "cost_insert",
            "eligibility_insert",
            "method_insert",
            "reject_mutation",
        )
    )
    + "\nDROP FUNCTION phase6a_hash(text);"
)


def refuse_populated_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        names = ",".join(f"assessments_{table}" for table in TABLES)
        cursor.execute(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
        checks = " OR ".join(f"EXISTS(SELECT 1 FROM assessments_{table})" for table in TABLES)
        cursor.execute(f"SELECT {checks}")
        if cursor.fetchone()[0]:
            raise RuntimeError("phase6a_populated_reverse_refused")


class Migration(migrations.Migration):
    dependencies = [("assessments", "0001_initial")]
    operations = [
        migrations.RunSQL(SQL, REVERSE),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
