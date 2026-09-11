from django.db import migrations

METHOD_SHA256 = "7a25477c45d9b2285f8e594c5bd0b7bb3f1e9f88babae50a58b7282604aeb262"
SQL = r"""
CREATE FUNCTION phase7_context_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p jsonb:=NEW.payload; req jsonb:=p->'request'; result jsonb:=p->'result'; packet research_frozenevidencepacket; section jsonb; claim jsonb;
BEGIN
 PERFORM pg_advisory_xact_lock(7007001);
 SELECT * INTO STRICT packet FROM research_frozenevidencepacket WHERE id=NEW.packet_id;
 PERFORM phase7_assert(NEW.digest=market_state_digest(p) AND p->>'version'='evidence-quality-v1'
  AND phase7_keys(p,ARRAY['version','packet_sha256','request','result'])
  AND p->>'packet_sha256'=packet.digest AND packet.payload->>'readiness'='ready'
  AND phase7_keys(req,ARRAY['method','input','prompt','schema','request_sha256'])
  AND market_state_digest(req->'method')='__METHOD__'
  AND market_state_digest(req->'prompt')=req->'method'->>'prompt_sha256'
  AND market_state_digest(req->'schema')=req->'method'->>'schema_sha256'
  AND req->'input'->>'packet_sha256'=packet.digest
  AND req->'input'->>'method_sha256'='__METHOD__'
  AND req->>'request_sha256'=market_state_digest(jsonb_build_array(req->'method',req->'input'))
  AND phase7_keys(result,ARRAY['method','request_sha256','returned_model','input_tokens','output_tokens','cost_usd','output'])
  AND result->'method'=req->'method' AND result->>'request_sha256'=req->>'request_sha256'
  AND result->>'returned_model'=req->'method'->>'requested_model'
  AND (result->>'input_tokens')::integer BETWEEN 0 AND 4000
  AND (result->>'output_tokens')::integer BETWEEN 0 AND 1800
  AND (result->>'cost_usd')::numeric=((result->>'input_tokens')::numeric*2+(result->>'output_tokens')::numeric*10)/1000000
  AND (result->>'cost_usd')::numeric<=0.03
  AND phase7_keys(result->'output',ARRAY['executive_summary','supporting_claims','contradicting_claims','uncertain_claims','conflict_interpretations','bounded_thesis','abstention_explanation','research_questions']));
 FOR section IN SELECT value FROM jsonb_each(result->'output') LOOP
  PERFORM phase7_assert(jsonb_typeof(section)='array' AND jsonb_array_length(section)<=3);
  FOR claim IN SELECT value FROM jsonb_array_elements(section) LOOP
   PERFORM phase7_assert(phase7_keys(claim,ARRAY['statement','relationship','kind','citations'])
    AND jsonb_typeof(claim->'statement')='string' AND length(claim->>'statement') BETWEEN 1 AND 600
    AND claim->>'relationship' IN ('supporting','contradicting','uncertain','conflict','research')
    AND claim->>'kind' IN ('fact','interpretation','hypothesis')
    AND jsonb_typeof(claim->'citations')='array' AND jsonb_array_length(claim->'citations') BETWEEN 1 AND 3);
  END LOOP;
 END LOOP;
 NEW.recorded_at:=clock_timestamp();
 RETURN NEW;
END; $$;
CREATE TRIGGER phase7_context_insert BEFORE INSERT ON research_evidencecontextresult FOR EACH ROW EXECUTE FUNCTION phase7_context_insert();
CREATE TRIGGER phase7_immutable BEFORE UPDATE OR DELETE ON research_evidencecontextresult FOR EACH ROW EXECUTE FUNCTION phase7_immutable();
CREATE TRIGGER phase7_no_truncate BEFORE TRUNCATE ON research_evidencecontextresult FOR EACH STATEMENT EXECUTE FUNCTION market_state_reject_truncate();
""".replace("__METHOD__", METHOD_SHA256)


def refuse_populated_reverse(apps, schema_editor):
    tables = (
        "evidencerightsreview",
        "exactevidence",
        "evidenceconflict",
        "frozenevidencepacket",
        "evidenceincident",
        "evidencecontextresult",
    )
    schema_editor.execute(
        "LOCK TABLE " + ",".join("research_" + t for t in tables) + " IN ACCESS EXCLUSIVE MODE"
    )
    with schema_editor.connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT EXISTS(SELECT 1 FROM research_{table})")
            if cursor.fetchone()[0]:
                raise RuntimeError("Phase7 populated evidence reversal refused")


class Migration(migrations.Migration):
    dependencies = [("research", "0020_phase7_context_result")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER phase7_context_insert ON research_evidencecontextresult; DROP TRIGGER phase7_immutable ON research_evidencecontextresult; DROP TRIGGER phase7_no_truncate ON research_evidencecontextresult; DROP FUNCTION phase7_context_insert();",
        ),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
