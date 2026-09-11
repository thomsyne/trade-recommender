"""Freeze legacy conflict knowledge conservatively, without rewriting history."""

from importlib import import_module

from django.db import migrations

SQL = r"""
CREATE FUNCTION phase7_conflicts(identity text, cutoff timestamptz) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object('digest',d,'known_at',t,'class',c,'changed_fields',f) ORDER BY d),'[]'::jsonb)
 FROM (
  SELECT x.digest d,x.recorded_at t,x.payload->>'class' c,x.payload->'changed_fields' f
  FROM research_evidenceconflict x JOIN research_exactevidence earlier ON earlier.id=x.earlier_id
  WHERE earlier.payload->>'canonical_hash'=identity AND x.recorded_at<=cutoff
  UNION ALL
  SELECT market_state_digest(jsonb_build_array('legacy-discrepancy',id)), observed_at,
   'unclassified_change', '[]'::jsonb
  FROM research_researchdiscrepancy WHERE entity_key='document:'||identity
   AND kind='conflict' AND observed_at<=cutoff
 ) facts
$$;
"""

# Frozen prior migration text, not runtime semantics. The original migration is
# unchanged; this forward definition expands provenance admission only.
BASE = import_module("research.migrations.0017_phase7_evidence_guards").SQL
START = BASE.index("CREATE FUNCTION phase7_insert()")
OLD = BASE[START:]
BEGIN = OLD.index("   SELECT coalesce(jsonb_agg(jsonb_build_object('digest',x.digest")
END = OLD.index("   -- Compare timestamps", BEGIN)
NEW = (
    OLD[:BEGIN]
    + "   actual := phase7_conflicts(a.payload->>'canonical_hash',NEW.cutoff);\n"
    + OLD[END:]
)
NEW = NEW.replace("CREATE FUNCTION phase7_insert()", "CREATE OR REPLACE FUNCTION phase7_insert()")
NEW = NEW.replace(
    "AND p->>'normalized_fact'=o.normalized_value AND p->>'source_item_id'=o.id::text",
    "AND p->>'normalized_fact'=o.normalized_value AND p->>'source_item_id'=o.id::text "
    "AND p->>'canonical_hash'=market_state_digest(jsonb_build_array('macro',o.series_id,to_char(o.observation_period,'YYYY-MM-DD'))) "
    "AND p->>'canonical_url'=r.url AND (p->>'first_observed_at')::timestamptz=r.fetched_at",
)
NEW = NEW.replace(
    "   c := e->'candidate';",
    r"""
   PERFORM phase7_assert(phase7_keys(e->'relevance',ARRAY['score','reasons'])
    AND jsonb_typeof(e->'relevance'->'score')='number' AND (e->'relevance'->>'score')::integer>=0
    AND jsonb_typeof(e->'relevance'->'reasons')='array'
    AND e->>'conflict_at_cutoff' IN ('none','nonmaterial','material','unknown','post-cutoff')
    AND jsonb_typeof(e->'rank')='number' AND (e->>'rank')::integer>0
    AND jsonb_typeof(e->'exclusions')='array' AND jsonb_typeof(e->'permitted_fields')='array'
    AND phase7_keys(e->'rights_by_field',ARRAY['headline','supplied_summary','normalized_fact','derived_label','url_attribution']));
   FOR k,v IN SELECT * FROM jsonb_each(e->'rights_by_field') LOOP
    PERFORM phase7_assert(phase7_keys(v,ARRAY['deterministic_processing','external_llm'])
      AND v->>'deterministic_processing' IN ('allowed','prohibited','unknown','review-required','expired','superseded')
      AND v->>'external_llm' IN ('allowed','prohibited','unknown','review-required','expired','superseded'));
   END LOOP;
   FOR v IN SELECT value FROM jsonb_array_elements(e->'exclusions') LOOP
    PERFORM phase7_assert(v #>> '{}' IN ('future','missing_publication_time','stale','retrieval_unavailable','irrelevant','rights_blocked','attribution_rights_blocked','derived_label_rights_blocked','required_field_rights_blocked','required_unresolved','duplicate_document','cap'));
   END LOOP;
   FOR v IN SELECT value FROM jsonb_array_elements(e->'permitted_fields') LOOP
    PERFORM phase7_assert(v #>> '{}' IN ('headline','supplied_summary','normalized_fact','derived_label','url_attribution'));
   END LOOP;
   c := e->'candidate';""",
)


class Migration(migrations.Migration):
    dependencies = [("research", "0018_phase7_serialized_changes")]
    operations = [
        migrations.RunSQL(
            SQL + NEW,
            OLD.replace(
                "CREATE FUNCTION phase7_insert()", "CREATE OR REPLACE FUNCTION phase7_insert()"
            )
            + "DROP FUNCTION phase7_conflicts(text,timestamptz);",
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            import_module(
                "research.migrations.0018_phase7_serialized_changes"
            ).refuse_populated_reverse,
        ),
    ]
