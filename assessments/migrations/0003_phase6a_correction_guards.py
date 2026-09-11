"""Forward-only Phase 6A v2 fail-closed admission and deterministic SQL projection."""

import importlib

from django.db import migrations

METHOD_DIGEST = "9ce72ba4fa5032d010266c06ce2928650bd31338398dee223b477c11c363d3fc"
EMPTY_DECISION = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
EMPTY_MANIFEST = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
EMPTY_PROVENANCE = "1eb0ba201ff0342fb6251107bbda084e1c86f0ce68a31964d23704181d28fca7"

REASONS = (
    "input_integrity_failure",
    "no_economically_admitted_strategy",
    "strategy_not_admitted_for_instrument",
    "strategy_role_cannot_originate_intent",
    "required_timeframe_unavailable",
    "m15_confirmation_unavailable",
    "required_evidence_not_ready",
    "event_state_unknown",
    "event_window_blocked",
    "technical_setup_absent",
    "trigger_pending",
    "trigger_rejected",
    "trigger_invalidated",
    "trigger_expired",
    "spread_unknown",
    "spread_exceeds_strategy_limit",
    "cost_evidence_missing",
    "cost_evidence_stale",
    "net_reward_nonpositive",
    "capacity_assessment_missing",
    "aggregate_capacity_exceeded",
    "currency_direction_capacity_exceeded",
    "conflicting_eligible_setups",
    "unsupported_intent_shape",
    "unchanged_duplicate_intent",
)

SQL = r"""
CREATE OR REPLACE FUNCTION phase6a_method_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.key IS DISTINCT FROM 'deterministic-multi-timeframe-assessment'
 OR NEW.version IS DISTINCT FROM '1.1.0'
 OR NEW.digest IS DISTINCT FROM '__METHOD__'
 OR NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/method-v2'
 OR NEW.payload->>'economic_admission' IS DISTINCT FROM 'unavailable_no_authoritative_phase55_contract'
 OR NEW.payload->>'cost_authority' IS DISTINCT FROM 'unavailable_no_immutable_source_contract'
 OR NEW.payload->>'capacity_authority' IS DISTINCT FROM 'unavailable_no_immutable_policy_source_contract'
 OR NEW.payload->>'activation' IS DISTINCT FROM 'forbidden'
 THEN RAISE EXCEPTION 'phase6a_method_v2_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at := clock_timestamp(); RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION phase6a_eligibility_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE code text; expected jsonb;
BEGIN
 SELECT i.code INTO STRICT code FROM market_instrument i WHERE i.id=NEW.instrument_id;
 expected:=jsonb_build_object(
   'schema','phase6a/eligibility-v1','instrument',code,
   'era','phase6a-canonical-empty-v1',
   'phase55_decision_sha256','__EMPTY_DECISION__',
   'phase55_manifest_sha256','__EMPTY_MANIFEST__',
   'admission_provenance_sha256','__EMPTY_PROVENANCE__','entries','[]'::jsonb);
 IF NEW.payload IS DISTINCT FROM expected
 OR NEW.digest IS DISTINCT FROM market_state_digest(expected)
 OR NEW.valid_until IS NOT NULL
 THEN RAISE EXCEPTION 'phase6a_no_authoritative_phase55_admission' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); NEW.valid_from:=NEW.recorded_at;
 IF NEW.decision_known_at>NEW.recorded_at
 THEN RAISE EXCEPTION 'phase6a_eligibility_chronology' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION phase6a_cost_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'phase6a_cost_authority_unavailable' USING ERRCODE='23514';
END; $$;

CREATE OR REPLACE FUNCTION phase6a_capacity_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'phase6a_capacity_authority_unavailable' USING ERRCODE='23514';
END; $$;

CREATE FUNCTION phase6a_expected_empty_output(snapshot_pk bigint) RETURNS jsonb LANGUAGE plpgsql STABLE
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p jsonb; monthly jsonb; event jsonb; macro jsonb; missing text[]:=ARRAY[]::text[];
        timeframe text; zones jsonb; htf jsonb; gates jsonb; htf_state text;
        event_known boolean; active_events text; reason_detail text;
BEGIN
 SELECT output_payload INTO STRICT p FROM market_marketstatesnapshot WHERE id=snapshot_pk;
 monthly:=coalesce(p->'monthly_context','{}'::jsonb);
 event:=coalesce(p->'event_state','{}'::jsonb);
 macro:=coalesce(p->'macro_regime',jsonb_build_object('state','unavailable'));
 IF monthly->>'state' IS DISTINCT FROM 'available' THEN missing:=array_append(missing,'monthly-context-v1'); END IF;
 FOREACH timeframe IN ARRAY ARRAY['W','D','H4','H1','M15'] LOOP
   IF p#>>ARRAY['granularities',timeframe,'state'] IS DISTINCT FROM 'available'
   THEN missing:=array_append(missing,timeframe); END IF;
 END LOOP;
 htf_state:=CASE WHEN cardinality(missing)=0 THEN 'available' ELSE 'unavailable' END;
 SELECT coalesce(jsonb_agg(jsonb_build_object('timeframe',t.tf)||z.value ORDER BY t.ord,z.ord),'[]'::jsonb)
 INTO zones
 FROM unnest(ARRAY['W','D','H4','H1']) WITH ORDINALITY t(tf,ord)
 CROSS JOIN LATERAL jsonb_array_elements(
   coalesce(p#>ARRAY['granularities',t.tf,'structure','support_resistance_zones','zones'],'[]'::jsonb)
 ) WITH ORDINALITY z(value,ord);
 htf:=jsonb_build_object(
   'W',coalesce(p#>'{granularities,W,trend}',p#>'{granularities,W}',jsonb_build_object('state','unavailable')),
   'D',coalesce(p#>'{granularities,D,trend}',p#>'{granularities,D}',jsonb_build_object('state','unavailable')),
   'H4',coalesce(p#>'{granularities,H4,trend}',p#>'{granularities,H4}',jsonb_build_object('state','unavailable')),
   'monthly',monthly,'macro',macro,'event',event,
   'sentiment',jsonb_build_object('state','unavailable','reason','no_frozen_sentiment_contract'));
 event_known:=event->>'state'='available' AND event->>'coverage'='attested_complete';
 SELECT coalesce(string_agg(value,',' ORDER BY value),'') INTO active_events
 FROM jsonb_array_elements_text(coalesce(event->'active_window_vintages','[]'::jsonb));
 reason_detail:=coalesce(event->>'reason_code',event->>'coverage','');
 SELECT jsonb_agg(jsonb_build_object(
   'reason',r.reason,
   'state',CASE
     WHEN r.reason='no_economically_admitted_strategy' THEN 'closed'
     WHEN r.reason='required_timeframe_unavailable' AND cardinality(missing)>0 THEN 'closed'
     WHEN r.reason='event_state_unknown' AND NOT event_known THEN 'closed'
     WHEN r.reason='event_window_blocked' AND active_events<>'' THEN 'closed'
     WHEN r.reason IN ('spread_unknown','cost_evidence_missing','net_reward_nonpositive',
       'capacity_assessment_missing','aggregate_capacity_exceeded','currency_direction_capacity_exceeded') THEN 'closed'
     ELSE 'available' END,
   'detail',CASE
     WHEN r.reason='no_economically_admitted_strategy' THEN 'canonical eligibility is empty'
     WHEN r.reason='required_timeframe_unavailable' THEN array_to_string(missing,',')
     WHEN r.reason='event_state_unknown' THEN CASE WHEN event_known THEN '' ELSE reason_detail END
     WHEN r.reason='event_window_blocked' THEN active_events
     WHEN r.reason='spread_unknown' THEN 'exact spread required'
     WHEN r.reason='cost_evidence_missing' THEN 'all exact components required'
     WHEN r.reason='net_reward_nonpositive' THEN 'unknown'
     WHEN r.reason IN ('aggregate_capacity_exceeded','currency_direction_capacity_exceeded') THEN 'unknown'
     ELSE '' END) ORDER BY r.ord)
 INTO gates FROM unnest(ARRAY[__REASONS__]::text[]) WITH ORDINALITY r(reason,ord);
 RETURN jsonb_build_object(
   'schema','phase6a/assessment-v2','status','closed','information_cutoff',p->'information_cutoff',
   'htf_regime',jsonb_build_object('state',htf_state,'values',htf),
   'major_zones',jsonb_build_object('state',htf_state,'values',zones),
   'eligible_strategies',jsonb_build_object('state','available','values','[]'::jsonb),
   'directional_triggers',jsonb_build_object('state','available','values',jsonb_build_object(
     'bull',jsonb_build_object('supporting','[]'::jsonb,'opposing','[]'::jsonb,'pending','[]'::jsonb,'rejected','[]'::jsonb),
     'bear',jsonb_build_object('supporting','[]'::jsonb,'opposing','[]'::jsonb,'pending','[]'::jsonb,'rejected','[]'::jsonb))),
   'mechanical_trigger',jsonb_build_object('state','unavailable','trigger','[]'::jsonb,
     'confirmation','null'::jsonb,'earliest_next_m15_entry','null'::jsonb,'broker_executable',false,'m1_inferred',false),
   'reward_and_cost',jsonb_build_object('state','unavailable','gross_r','null'::jsonb,
     'components','null'::jsonb,'cost_identity','null'::jsonb,'net_r','null'::jsonb),
   'capacity',jsonb_build_object('state','unavailable','identity','null'::jsonb,
     'policy_identity','null'::jsonb,'source_identity','null'::jsonb,'aggregate','null'::jsonb,'currency_legs','null'::jsonb),
   'terminal_state',jsonb_build_object('state','unavailable','invalidation','null'::jsonb,
     'expires_at','null'::jsonb,'supersession','append_only_candidate_link'),
   'decision',jsonb_build_object('state','closed','primary_reason','no_economically_admitted_strategy','gates',gates));
END; $$;

CREATE OR REPLACE FUNCTION phase6a_assessment_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE s market_marketstatesnapshot; e assessments_eligibilitysnapshot;
        m assessments_assessmentmethod; expected_manifest jsonb; expected_output jsonb;
BEGIN
 SELECT * INTO STRICT s FROM market_marketstatesnapshot WHERE id=NEW.snapshot_id;
 SELECT * INTO STRICT e FROM assessments_eligibilitysnapshot WHERE id=NEW.eligibility_id;
 SELECT * INTO STRICT m FROM assessments_assessmentmethod WHERE id=NEW.method_id;
 expected_manifest:=jsonb_build_object(
   'schema','phase6a/input-manifest-v1','method',m.digest,
   'snapshot',jsonb_build_object('id',s.id,'identity',s.idempotency_key),
   'eligibility',jsonb_build_object(
     'digest',e.digest,
     'decision_known_at',to_char(e.decision_known_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00',
     'valid_from',to_char(e.valid_from AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00',
     'valid_until','null'::jsonb,
     'recorded_at',to_char(e.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'),
   'evaluations','[]'::jsonb,
   'cost','null'::jsonb,'capacity','null'::jsonb,'evidence','null'::jsonb);
 expected_output:=phase6a_expected_empty_output(s.id);
 IF m.digest IS DISTINCT FROM '__METHOD__'
 OR m.digest IS DISTINCT FROM market_state_digest(m.payload)
 OR NOT EXISTS(SELECT 1 FROM market_marketstatedefinition d WHERE d.id=s.definition_id
      AND d.definition_sha256='9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3')
 OR s.input_manifest_sha256 IS DISTINCT FROM market_state_digest(s.input_manifest)
 OR s.output_sha256 IS DISTINCT FROM market_state_digest(s.output_payload)
 OR e.digest IS DISTINCT FROM market_state_digest(e.payload)
 OR jsonb_array_length(e.payload->'entries')<>0
 OR NEW.information_cutoff IS DISTINCT FROM s.information_cutoff
 OR e.instrument_id IS DISTINCT FROM s.instrument_id
 OR e.valid_from IS DISTINCT FROM e.recorded_at OR e.valid_until IS NOT NULL
 OR e.decision_known_at>e.recorded_at OR e.recorded_at>NEW.information_cutoff
 OR NEW.cost_id IS NOT NULL OR NEW.capacity_id IS NOT NULL OR NEW.evidence_packet_id IS NOT NULL
 OR NEW.input_manifest IS DISTINCT FROM expected_manifest
 OR NEW.input_digest IS DISTINCT FROM market_state_digest(expected_manifest)
 OR NEW.output IS DISTINCT FROM expected_output
 OR NEW.output_digest IS DISTINCT FROM market_state_digest(expected_output)
 THEN RAISE EXCEPTION 'phase6a_assessment_v2_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;

CREATE OR REPLACE FUNCTION phase6a_candidate_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'phase6a_candidate_requires_authoritative_eligibility' USING ERRCODE='23514';
END; $$;

CREATE OR REPLACE FUNCTION phase6a_supersession_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p assessments_eligibletradeintentcandidate; s assessments_eligibletradeintentcandidate;
BEGIN
 SELECT * INTO STRICT p FROM assessments_eligibletradeintentcandidate WHERE id=NEW.predecessor_id;
 SELECT * INTO STRICT s FROM assessments_eligibletradeintentcandidate WHERE id=NEW.successor_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('phase6a:predecessor:'||p.id::text,0));
 IF p.id=s.id OR s.predecessor_id IS DISTINCT FROM p.id OR p.semantic_identity=s.semantic_identity
 OR p.assessment_id=s.assessment_id
 OR p.payload->>'strategy' IS DISTINCT FROM s.payload->>'strategy'
 OR p.payload->>'direction' IS DISTINCT FROM s.payload->>'direction'
 OR (SELECT instrument_id FROM market_marketstatesnapshot ms JOIN assessments_multitimeframeassessment a ON a.snapshot_id=ms.id WHERE a.id=p.assessment_id)
    IS DISTINCT FROM
    (SELECT instrument_id FROM market_marketstatesnapshot ms JOIN assessments_multitimeframeassessment a ON a.snapshot_id=ms.id WHERE a.id=s.assessment_id)
 OR NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload IS DISTINCT FROM jsonb_build_object(
      'schema','phase6a/intent-supersession-v1','predecessor',p.digest,'successor',s.digest,
      'observed_at_cutoff',to_char((SELECT information_cutoff FROM assessments_multitimeframeassessment WHERE id=s.assessment_id)
        AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00')
 THEN RAISE EXCEPTION 'phase6a_supersession_scope_contract' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM assessments_intentsupersession x WHERE x.predecessor_id=p.id)
 THEN RAISE EXCEPTION 'phase6a_predecessor_already_superseded' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_candidate_pairing() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE candidate_id bigint; expected_predecessor_id bigint; pairing_count int;
BEGIN
 candidate_id:=CASE WHEN TG_TABLE_NAME='assessments_intentsupersession' THEN NEW.successor_id ELSE NEW.id END;
 SELECT c.predecessor_id INTO STRICT expected_predecessor_id
 FROM assessments_eligibletradeintentcandidate c WHERE c.id=candidate_id;
 SELECT count(*) INTO pairing_count FROM assessments_intentsupersession x
 WHERE x.successor_id=candidate_id AND x.predecessor_id IS NOT DISTINCT FROM expected_predecessor_id;
 IF (expected_predecessor_id IS NULL AND pairing_count<>0)
 OR (expected_predecessor_id IS NOT NULL AND pairing_count<>1)
 THEN RAISE EXCEPTION 'phase6a_candidate_supersession_pairing' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$;

CREATE CONSTRAINT TRIGGER phase6a_candidate_pairing
AFTER INSERT ON assessments_eligibletradeintentcandidate DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION phase6a_candidate_pairing();
CREATE CONSTRAINT TRIGGER phase6a_supersession_pairing
AFTER INSERT ON assessments_intentsupersession DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION phase6a_candidate_pairing();
"""

SQL = (
    SQL.replace("__METHOD__", METHOD_DIGEST)
    .replace("__EMPTY_DECISION__", EMPTY_DECISION)
    .replace("__EMPTY_MANIFEST__", EMPTY_MANIFEST)
    .replace("__EMPTY_PROVENANCE__", EMPTY_PROVENANCE)
    .replace("__REASONS__", ",".join(f"'{reason}'" for reason in REASONS))
)

_OLD = importlib.import_module("assessments.migrations.0002_phase6a_guards").SQL
OLD_FUNCTIONS = _OLD.split("CREATE TRIGGER phase6a_validate", 1)[0].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"
)
REVERSE = (
    """
DROP TRIGGER phase6a_candidate_pairing ON assessments_eligibletradeintentcandidate;
DROP TRIGGER phase6a_supersession_pairing ON assessments_intentsupersession;
DROP FUNCTION phase6a_candidate_pairing();
DROP FUNCTION phase6a_expected_empty_output(bigint);
"""
    + OLD_FUNCTIONS
)


def refuse_populated_reverse(apps, schema_editor):
    tables = (
        "assessmentmethod",
        "eligibilitysnapshot",
        "costevidence",
        "capacityassessment",
        "multitimeframeassessment",
        "eligibletradeintentcandidate",
        "intentsupersession",
    )
    with schema_editor.connection.cursor() as cursor:
        names = ",".join(f"assessments_{table}" for table in tables)
        cursor.execute(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT "
            + " OR ".join(f"EXISTS(SELECT 1 FROM assessments_{table})" for table in tables)
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("phase6a_populated_correction_reverse_refused")


class Migration(migrations.Migration):
    dependencies = [("assessments", "0002_phase6a_guards")]
    operations = [
        migrations.RunSQL(SQL, REVERSE),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
