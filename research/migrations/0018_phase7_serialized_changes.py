"""Serialize cutoff admission and append revision facts automatically."""

from django.db import migrations

TABLES = (
    "evidencerightsreview",
    "exactevidence",
    "evidenceconflict",
    "frozenevidencepacket",
    "evidenceincident",
)

SQL = r"""
CREATE FUNCTION phase7_lock() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 PERFORM phase7_assert(current_setting('transaction_isolation')='read committed');
 PERFORM pg_advisory_xact_lock(7007001);
 RETURN NEW;
END; $$;

CREATE FUNCTION phase7_append_change() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE prior research_exactevidence; fields jsonb; category text; body jsonb;
BEGIN
 SELECT * INTO prior FROM research_exactevidence WHERE id<>NEW.id
  AND payload->>'canonical_hash'=NEW.payload->>'canonical_hash'
  ORDER BY recorded_at DESC,id DESC LIMIT 1;
 IF prior.id IS NULL THEN RETURN NEW; END IF;
 SELECT coalesce(jsonb_agg(key ORDER BY ord),'[]'::jsonb) INTO fields FROM
  unnest(ARRAY['headline','published_at','supplied_summary','normalized_fact']) WITH ORDINALITY f(key,ord)
  WHERE prior.payload->key IS DISTINCT FROM NEW.payload->key;
 category := CASE WHEN fields='[]'::jsonb THEN 'immaterial_repeat'
  WHEN fields='["headline"]'::jsonb THEN 'title_edit'
  WHEN fields='["published_at"]'::jsonb THEN 'publication_time_edit'
  WHEN fields='["supplied_summary"]'::jsonb THEN 'summary_edit' ELSE 'unclassified_change' END;
 body := jsonb_build_object('version','evidence-quality-v1','earlier',prior.digest,'later',NEW.digest,'class',category,'changed_fields',fields);
 INSERT INTO research_evidenceconflict(earlier_id,later_id,recorded_at,digest,payload)
 VALUES(prior.id,NEW.id,clock_timestamp(),market_state_digest(body),body)
 ON CONFLICT(digest) DO NOTHING;
 RETURN NEW;
END; $$;
CREATE TRIGGER phase7_append_change AFTER INSERT ON research_exactevidence
FOR EACH ROW EXECUTE FUNCTION phase7_append_change();
"""


def refuse_populated_reverse(apps, schema_editor):
    schema_editor.execute(
        "LOCK TABLE " + ",".join("research_" + t for t in TABLES) + " IN ACCESS EXCLUSIVE MODE"
    )
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"SELECT EXISTS(SELECT 1 FROM research_{table})")
            if cursor.fetchone()[0]:
                raise RuntimeError("Phase7 populated evidence reversal refused")


class Migration(migrations.Migration):
    dependencies = [("research", "0017_phase7_evidence_guards")]
    operations = [
        migrations.RunSQL(
            SQL,
            "DROP TRIGGER phase7_append_change ON research_exactevidence; DROP FUNCTION phase7_append_change(); DROP FUNCTION phase7_lock();",
        ),
        *[
            migrations.RunSQL(
                f"CREATE TRIGGER phase7_a_lock BEFORE INSERT ON research_{t} FOR EACH ROW EXECUTE FUNCTION phase7_lock(); DROP TRIGGER phase7_no_truncate ON research_{t}; CREATE TRIGGER phase7_no_truncate BEFORE TRUNCATE ON research_{t} FOR EACH STATEMENT EXECUTE FUNCTION market_state_reject_truncate();",
                f"DROP TRIGGER phase7_a_lock ON research_{t}; DROP TRIGGER phase7_no_truncate ON research_{t}; CREATE TRIGGER phase7_no_truncate BEFORE TRUNCATE ON research_{t} FOR EACH STATEMENT EXECUTE FUNCTION phase7_immutable();",
            )
            for t in TABLES
        ],
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
