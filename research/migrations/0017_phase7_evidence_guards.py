"""Prospective immutable evidence admission; no existing table/data changes."""

from django.db import migrations

TABLES = (
    "evidencerightsreview",
    "exactevidence",
    "evidenceconflict",
    "frozenevidencepacket",
    "evidenceincident",
)

SQL = r"""
CREATE FUNCTION phase7_keys(v jsonb, keys text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(v)='object' AND v ?& keys AND
   (SELECT count(*) FROM jsonb_object_keys(v))=cardinality(keys), false)
$$;

CREATE FUNCTION phase7_assert(ok boolean) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 IF ok IS DISTINCT FROM true THEN
  RAISE EXCEPTION 'phase7_admission' USING ERRCODE='23514';
 END IF;
END; $$;

CREATE FUNCTION phase7_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'phase7 evidence is append-only; must not be truncated' USING ERRCODE='23514'; END;
$$;

CREATE FUNCTION phase7_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE p jsonb := NEW.payload; k text; v jsonb; c jsonb; e jsonb;
 r research_rawretrieval; s research_sourcepolicy; d research_researchdocument;
 o research_macroobservation; a research_exactevidence; b research_exactevidence;
 w research_evidencerightsreview; prior research_evidencerightsreview;
 cf research_evidenceconflict; ids text[] := ARRAY[]::text[];
 actual jsonb; fields jsonb; category text; n integer; sourceid bigint;
BEGIN
 PERFORM phase7_assert(NEW.digest = market_state_digest(p));
 NEW.recorded_at := clock_timestamp();
 PERFORM phase7_assert(coalesce(p->>'version',p->>'schema')='evidence-quality-v1');
 IF TG_TABLE_NAME='research_evidencerightsreview' THEN
  PERFORM phase7_assert(phase7_keys(p,ARRAY['version','source_id','processor','terms_url','terms_sha256','reviewer','reviewed_at','expires_at','jurisdiction','attribution','retention','deletion','rationale','decisions','supersedes']));
  PERFORM phase7_assert((p->>'source_id')::bigint=NEW.source_id AND p->>'terms_sha256' ~ '^[a-f0-9]{64}$'
   AND p->>'terms_url' LIKE 'https://%' AND (p->>'reviewed_at')::timestamptz<=NEW.recorded_at
   AND (p->>'expires_at')::timestamptz>(p->>'reviewed_at')::timestamptz);
  FOREACH k IN ARRAY ARRAY['processor','reviewer','jurisdiction','attribution','retention','deletion','rationale'] LOOP
   PERFORM phase7_assert(jsonb_typeof(p->k)='string' AND length(p->>k) BETWEEN 1 AND 2000);
  END LOOP;
  PERFORM 1 FROM market_sourceregistry WHERE id=NEW.source_id FOR UPDATE;
  SELECT * INTO prior FROM research_evidencerightsreview WHERE source_id=NEW.source_id
    AND payload->>'processor'=p->>'processor' ORDER BY recorded_at DESC,id DESC LIMIT 1;
  PERFORM phase7_assert((p->>'supersedes') IS NOT DISTINCT FROM prior.digest);
  PERFORM phase7_assert(phase7_keys(p->'decisions',ARRAY['raw_body','headline','supplied_summary','normalized_fact','derived_label','url_attribution']));
  FOR k,v IN SELECT * FROM jsonb_each(p->'decisions') LOOP
   PERFORM phase7_assert(phase7_keys(v,ARRAY['private_storage','private_display','deterministic_processing','external_llm','internal_report','notification','redistribution']));
   FOR e IN SELECT value FROM jsonb_each(v) LOOP
    PERFORM phase7_assert(e #>> '{}' IN ('allowed','prohibited','unknown','review-required','expired','superseded'));
   END LOOP;
  END LOOP;
 ELSIF TG_TABLE_NAME='research_exactevidence' THEN
  PERFORM phase7_assert(phase7_keys(p,ARRAY['version','kind','document_id','observation_id','retrieval_id','retrieval_sha256','source_id','source_item_id','canonical_hash','canonical_url','headline','supplied_summary','normalized_fact','published_at','first_observed_at','retrieved_at','language','content_type','storage_review_sha256','quality']));
  SELECT * INTO STRICT r FROM research_rawretrieval WHERE id=NEW.retrieval_id;
  SELECT * INTO STRICT s FROM research_sourcepolicy WHERE id=r.source_policy_id;
  SELECT * INTO STRICT w FROM research_evidencerightsreview WHERE id=NEW.storage_review_id;
  PERFORM phase7_assert((p->>'retrieval_id')::bigint=r.id AND (p->>'source_id')::bigint=s.source_id
    AND p->>'retrieval_sha256'=r.body_sha256 AND r.body_sha256=encode(sha256(r.body),'hex')
    AND (p->>'retrieved_at')::timestamptz=r.fetched_at AND r.fetched_at<=NEW.recorded_at
    AND p->>'content_type'=r.content_type AND p->>'storage_review_sha256'=w.digest
    AND w.source_id=s.source_id AND w.payload->>'processor'='local'
    AND (w.payload->>'expires_at')::timestamptz>NEW.recorded_at);
  SELECT * INTO prior FROM research_evidencerightsreview WHERE source_id=s.source_id AND payload->>'processor'='local' ORDER BY recorded_at DESC,id DESC LIMIT 1;
  PERFORM phase7_assert(prior.id=w.id);
  FOREACH k IN ARRAY ARRAY['source_item_id','canonical_url','headline','supplied_summary','normalized_fact','language','content_type'] LOOP
   PERFORM phase7_assert(jsonb_typeof(p->k)='string' AND length(p->>k)<=12000);
  END LOOP;
  FOREACH k IN ARRAY ARRAY['headline','supplied_summary','normalized_fact','url_attribution'] LOOP
   IF k='url_attribution' OR p->>k<>'' THEN
    PERFORM phase7_assert(w.payload->'decisions'->k->>'private_storage'='allowed');
   END IF;
  END LOOP;
  PERFORM phase7_assert(phase7_keys(p->'quality',ARRAY['retrieval_integrity','timestamp_precision','source_tier','directness','corroboration']));
  PERFORM phase7_assert(p->'quality'->>'retrieval_integrity' IN ('hash_checked','unknown','rejected')
   AND p->'quality'->>'timestamp_precision' IN ('provider_exact','date_only','retrieval_only','unknown')
   AND p->'quality'->>'source_tier' IN ('primary','secondary','unknown')
   AND p->'quality'->>'directness' IN ('direct','reported','unknown')
   AND p->'quality'->>'corroboration' IN ('independent','single_source','unknown'));
  IF NEW.document_id IS NOT NULL THEN
   SELECT * INTO STRICT d FROM research_researchdocument WHERE id=NEW.document_id;
   PERFORM phase7_assert(NEW.observation_id IS NULL AND p->>'kind'='news'
    AND (p->>'document_id')::bigint=d.id AND p->'observation_id'='null'::jsonb
    AND p->>'canonical_hash'=d.canonical_hash AND p->>'canonical_url'=d.canonical_url
    AND (p->>'first_observed_at')::timestamptz=d.first_observed_at AND p->>'normalized_fact'='');
  ELSE
   SELECT * INTO STRICT o FROM research_macroobservation WHERE id=NEW.observation_id;
   PERFORM phase7_assert(p->>'kind'='macro' AND p->'document_id'='null'::jsonb
    AND (p->>'observation_id')::bigint=o.id AND o.retrieval_id=r.id
    AND p->>'normalized_fact'=o.normalized_value AND p->>'source_item_id'=o.id::text
    AND (p->>'published_at')::timestamptz=o.available_at);
  END IF;
 ELSIF TG_TABLE_NAME='research_evidenceconflict' THEN
  PERFORM phase7_assert(phase7_keys(p,ARRAY['version','earlier','later','class','changed_fields']));
  SELECT * INTO STRICT a FROM research_exactevidence WHERE id=NEW.earlier_id;
  SELECT * INTO STRICT b FROM research_exactevidence WHERE id=NEW.later_id;
  PERFORM phase7_assert(p->>'earlier'=a.digest AND p->>'later'=b.digest AND a.payload->>'canonical_hash'=b.payload->>'canonical_hash' AND a.recorded_at<=b.recorded_at);
  SELECT coalesce(jsonb_agg(key ORDER BY ord),'[]'::jsonb) INTO fields FROM
   unnest(ARRAY['headline','published_at','supplied_summary','normalized_fact']) WITH ORDINALITY f(key,ord)
   WHERE a.payload->key IS DISTINCT FROM b.payload->key;
  PERFORM phase7_assert(p->'changed_fields'=fields);
  category := CASE WHEN fields='[]'::jsonb THEN CASE WHEN a.digest=b.digest THEN 'exact_duplicate' ELSE 'immaterial_repeat' END
   WHEN fields='["headline"]'::jsonb THEN 'title_edit'
   WHEN fields='["published_at"]'::jsonb THEN 'publication_time_edit'
   WHEN fields='["supplied_summary"]'::jsonb THEN 'summary_edit' ELSE 'unclassified_change' END;
  PERFORM phase7_assert(p->>'class'=category OR p->>'class' IN ('provider_correction','material_disagreement','retraction'));
 ELSIF TG_TABLE_NAME='research_frozenevidencepacket' THEN
  PERFORM phase7_assert(phase7_keys(p,ARRAY['schema','policies','instrument','cutoff','required_ids','entries','candidate_count','included_count','excluded_counts','unavailable_required','readiness']));
  PERFORM phase7_assert((p->>'cutoff')::timestamptz=NEW.cutoff AND NEW.cutoff<=NEW.recorded_at
   AND p->>'instrument'=(SELECT code FROM market_instrument WHERE id=NEW.instrument_id)
   AND p->'policies'='{"rights":"evidence-quality-v1","relevance":"evidence-quality-v1","conflict":"evidence-quality-v1","packet":"evidence-quality-v1"}'::jsonb
   AND jsonb_typeof(p->'entries')='array' AND jsonb_typeof(p->'required_ids')='array'
   AND jsonb_typeof(p->'unavailable_required')='array' AND jsonb_typeof(p->'excluded_counts')='object'
   AND p->>'readiness' IN ('ready','abstain') AND (p->>'included_count')::integer BETWEEN 0 AND 20);
  FOR e IN SELECT value FROM jsonb_array_elements(p->'entries') LOOP
   PERFORM phase7_assert(phase7_keys(e,ARRAY['candidate','conflict_at_cutoff','relevance','rights_by_field','permitted_fields','exclusions','rank']));
   c := e->'candidate';
   PERFORM phase7_assert(phase7_keys(c,ARRAY['id','representation','known_at','rights','rights_known_at','conflicts','role']));
   PERFORM phase7_assert(NOT c->>'id'=ANY(ids)); ids := array_append(ids,c->>'id');
   SELECT * INTO STRICT a FROM research_exactevidence WHERE digest=c->>'id';
   PERFORM phase7_assert(c->'representation'=a.payload AND (c->>'known_at')::timestamptz=a.recorded_at AND a.recorded_at<=NEW.cutoff);
   sourceid := (a.payload->>'source_id')::bigint;
   SELECT * INTO w FROM research_evidencerightsreview WHERE source_id=sourceid AND payload->>'processor'='anthropic' AND recorded_at<=NEW.cutoff ORDER BY recorded_at DESC,id DESC LIMIT 1;
   PERFORM phase7_assert(c->'rights'=coalesce(w.payload,'null'::jsonb) AND (c->>'rights_known_at')::timestamptz IS NOT DISTINCT FROM w.recorded_at);
   SELECT coalesce(jsonb_agg(jsonb_build_object('digest',x.digest,'known_at',x.recorded_at,'class',x.payload->>'class','changed_fields',x.payload->'changed_fields') ORDER BY x.digest),'[]'::jsonb)
    INTO actual FROM research_evidenceconflict x JOIN research_exactevidence earlier ON earlier.id=x.earlier_id
    WHERE earlier.payload->>'canonical_hash'=a.payload->>'canonical_hash' AND x.recorded_at<=NEW.cutoff;
   -- Compare timestamps semantically; Python uses explicit UTC, SQL emits +00:00.
   PERFORM phase7_assert(jsonb_array_length(c->'conflicts')=jsonb_array_length(actual));
   FOR v IN SELECT value FROM jsonb_array_elements(c->'conflicts') LOOP
    PERFORM phase7_assert(EXISTS(SELECT 1 FROM jsonb_array_elements(actual) x WHERE x->>'digest'=v->>'digest' AND (x->>'known_at')::timestamptz=(v->>'known_at')::timestamptz AND x->'class'=v->'class' AND x->'changed_fields'=v->'changed_fields'));
   END LOOP;
   PERFORM phase7_assert(c->>'role' IN ('required','contextual','optional') AND ((c->>'role'='required')=(p->'required_ids' ? (c->>'id'))));
  END LOOP;
  SELECT count(*) INTO n FROM research_exactevidence WHERE recorded_at<=NEW.cutoff;
  PERFORM phase7_assert(n=cardinality(ids) AND (p->>'candidate_count')::integer=n);
 ELSIF TG_TABLE_NAME='research_evidenceincident' THEN
  PERFORM phase7_assert(phase7_keys(p,ARRAY['version','document','class','fields','change_sha256','window','message']));
  SELECT * INTO STRICT cf FROM research_evidenceconflict WHERE id=NEW.conflict_id;
  SELECT * INTO STRICT a FROM research_exactevidence WHERE id=cf.earlier_id;
  SELECT * INTO STRICT b FROM research_exactevidence WHERE id=cf.later_id;
  SELECT coalesce(jsonb_agg(value ORDER BY value),'[]'::jsonb) INTO fields FROM jsonb_array_elements(cf.payload->'changed_fields');
  SELECT coalesce(jsonb_object_agg(key,jsonb_build_array(a.payload->key,b.payload->key)),'{}'::jsonb) INTO actual FROM jsonb_array_elements_text(fields) f(key);
  PERFORM phase7_assert(p->>'document'=a.payload->>'canonical_hash' AND p->>'class'=cf.payload->>'class'
   AND p->'fields'=fields AND p->>'change_sha256'=market_state_digest(actual)
   AND (p->>'window')::bigint=floor(extract(epoch FROM cf.recorded_at)/86400)::bigint
   AND p->>'message'='Evidence discrepancy recorded; review required.');
 END IF;
 RETURN NEW;
END; $$;
"""


def reverse(apps, schema_editor):
    for table in TABLES:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f"SELECT EXISTS(SELECT 1 FROM research_{table})")
            if cursor.fetchone()[0]:
                raise RuntimeError("Phase7 populated evidence reversal refused")
    for table in TABLES:
        schema_editor.execute(
            f"DROP TRIGGER phase7_insert ON research_{table}; DROP TRIGGER phase7_immutable ON research_{table}; DROP TRIGGER phase7_no_truncate ON research_{table};"
        )
    schema_editor.execute(
        "DROP FUNCTION phase7_insert(); DROP FUNCTION phase7_immutable(); DROP FUNCTION phase7_assert(boolean); DROP FUNCTION phase7_keys(jsonb,text[]);"
    )


class Migration(migrations.Migration):
    dependencies = [("research", "0016_phase7_evidence_records")]
    operations = [
        migrations.RunSQL(SQL, migrations.RunSQL.noop),
        *[
            migrations.RunSQL(
                f"CREATE TRIGGER phase7_insert BEFORE INSERT ON research_{t} FOR EACH ROW EXECUTE FUNCTION phase7_insert(); CREATE TRIGGER phase7_immutable BEFORE UPDATE OR DELETE ON research_{t} FOR EACH ROW EXECUTE FUNCTION phase7_immutable(); CREATE TRIGGER phase7_no_truncate BEFORE TRUNCATE ON research_{t} FOR EACH STATEMENT EXECUTE FUNCTION phase7_immutable();",
                migrations.RunSQL.noop,
            )
            for t in TABLES
        ],
        migrations.RunPython(migrations.RunPython.noop, reverse),
    ]
