"""Require canonical eligibility at assessment admission and register method 1.2.0."""

import importlib

from django.db import migrations

METHOD_DIGEST = "95bc41c6d6dfcc07f96ac7ec2982ec1f3deea58806cc6ad7581af987efa399e8"
EMPTY_DECISION = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
EMPTY_MANIFEST = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
EMPTY_PROVENANCE = "1eb0ba201ff0342fb6251107bbda084e1c86f0ce68a31964d23704181d28fca7"

SQL = r"""
CREATE OR REPLACE FUNCTION phase6a_method_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.key IS DISTINCT FROM 'deterministic-multi-timeframe-assessment'
 OR NEW.version IS DISTINCT FROM '1.2.0'
 OR NEW.digest IS DISTINCT FROM '__METHOD__'
 OR NEW.digest IS DISTINCT FROM market_state_digest(NEW.payload)
 OR NEW.payload->>'schema' IS DISTINCT FROM 'phase6a/method-v2'
 OR NEW.payload->>'economic_admission' IS DISTINCT FROM 'unavailable_no_authoritative_phase55_contract'
 OR NEW.payload->>'cost_authority' IS DISTINCT FROM 'unavailable_no_immutable_source_contract'
 OR NEW.payload->>'capacity_authority' IS DISTINCT FROM 'unavailable_no_immutable_policy_source_contract'
 OR NEW.payload->>'activation' IS DISTINCT FROM 'forbidden'
 THEN RAISE EXCEPTION 'phase6a_method_v12_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;

CREATE FUNCTION phase6a_expected_empty_eligibility(instrument_pk bigint) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT jsonb_build_object(
   'schema','phase6a/eligibility-v1','instrument',i.code,
   'era','phase6a-canonical-empty-v1',
   'phase55_decision_sha256','__EMPTY_DECISION__',
   'phase55_manifest_sha256','__EMPTY_MANIFEST__',
   'admission_provenance_sha256','__EMPTY_PROVENANCE__','entries','[]'::jsonb)
 FROM market_instrument i WHERE i.id=instrument_pk
$$;

CREATE OR REPLACE FUNCTION phase6a_assessment_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE s market_marketstatesnapshot; e assessments_eligibilitysnapshot;
        m assessments_assessmentmethod; expected_manifest jsonb; expected_output jsonb;
        expected_eligibility jsonb;
BEGIN
 SELECT * INTO STRICT s FROM market_marketstatesnapshot WHERE id=NEW.snapshot_id;
 SELECT * INTO STRICT e FROM assessments_eligibilitysnapshot WHERE id=NEW.eligibility_id;
 SELECT * INTO STRICT m FROM assessments_assessmentmethod WHERE id=NEW.method_id;
 expected_eligibility:=phase6a_expected_empty_eligibility(s.instrument_id);
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
 OR e.instrument_id IS DISTINCT FROM s.instrument_id
 OR e.payload IS DISTINCT FROM expected_eligibility
 OR e.digest IS DISTINCT FROM market_state_digest(expected_eligibility)
 OR NEW.information_cutoff IS DISTINCT FROM s.information_cutoff
 OR e.valid_from IS DISTINCT FROM e.recorded_at OR e.valid_until IS NOT NULL
 OR e.decision_known_at>e.recorded_at OR e.recorded_at>NEW.information_cutoff
 OR NEW.cost_id IS NOT NULL OR NEW.capacity_id IS NOT NULL OR NEW.evidence_packet_id IS NOT NULL
 OR NEW.input_manifest IS DISTINCT FROM expected_manifest
 OR NEW.input_digest IS DISTINCT FROM market_state_digest(expected_manifest)
 OR NEW.output IS DISTINCT FROM expected_output
 OR NEW.output_digest IS DISTINCT FROM market_state_digest(expected_output)
 THEN RAISE EXCEPTION 'phase6a_assessment_v12_contract' USING ERRCODE='23514'; END IF;
 NEW.recorded_at:=clock_timestamp(); RETURN NEW;
END; $$;
"""

SQL = (
    SQL.replace("__METHOD__", METHOD_DIGEST)
    .replace("__EMPTY_DECISION__", EMPTY_DECISION)
    .replace("__EMPTY_MANIFEST__", EMPTY_MANIFEST)
    .replace("__EMPTY_PROVENANCE__", EMPTY_PROVENANCE)
)


def _function(sql, name):
    start = sql.index(f"CREATE OR REPLACE FUNCTION {name}")
    end = sql.index("\n\nCREATE", start)
    return sql[start:end] + "\n"


_OLD = importlib.import_module("assessments.migrations.0003_phase6a_correction_guards").SQL
REVERSE = (
    _function(_OLD, "phase6a_method_insert")
    + _function(_OLD, "phase6a_assessment_insert")
    + "DROP FUNCTION phase6a_expected_empty_eligibility(bigint);\n"
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
            raise RuntimeError("phase6a_populated_closure_reverse_refused")


class Migration(migrations.Migration):
    dependencies = [("assessments", "0003_phase6a_correction_guards")]
    operations = [
        migrations.RunSQL(SQL, REVERSE),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
