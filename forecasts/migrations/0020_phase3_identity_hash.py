from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_canonical_json(value jsonb) RETURNS text AS $$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN SELECT '{'||coalesce(string_agg(to_jsonb(key)::text||':'||phase3_canonical_json(val),',' ORDER BY key COLLATE "C"),'')||'}' INTO result FROM jsonb_each(value) item(key,val);
 WHEN 'array' THEN SELECT '['||coalesce(string_agg(phase3_canonical_json(val),',' ORDER BY ord),'')||']' INTO result FROM jsonb_array_elements(value) WITH ORDINALITY item(val,ord);
 ELSE result:=value::text;
 END CASE;
 RETURN result;
END; $$ LANGUAGE plpgsql IMMUTABLE STRICT;
CREATE FUNCTION phase3_target_hash() RETURNS trigger AS $$
DECLARE c market_candle%ROWTYPE; tc forecasts_targetcontract%ROWTYPE; code text; material jsonb;
BEGIN
 SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.reference_candle_id;
 SELECT * INTO STRICT tc FROM forecasts_targetcontract WHERE id=NEW.target_contract_id;
 SELECT instrument.code INTO STRICT code FROM market_instrument instrument WHERE id=NEW.instrument_id;
 material:=jsonb_build_object('instrument',code,'contract',jsonb_build_array(tc.key,tc.version),'product',tc.product,
 'definition',NEW.definition_sha256,'reference',to_char(c.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00',
 'content',NEW.reference_content_sha256,'midpoint',NEW.reference_midpoint::text,'band',NEW.neutral_band::text,
 'horizon',NEW.horizon_sessions,'cutoff',to_char(NEW.information_cutoff AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00',
 'resolution',NEW.resolution_method,'neutral_rule',NEW.neutral_rule);
 IF NEW.definition_sha256<>encode(sha256(convert_to(phase3_canonical_json(tc.definition),'UTF8')),'hex')
 OR NEW.identity_sha256<>encode(sha256(convert_to(phase3_canonical_json(material),'UTF8')),'hex')
 THEN RAISE EXCEPTION 'target_hash_mismatch'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_hash_validate BEFORE INSERT ON forecasts_targetoccurrence FOR EACH ROW EXECUTE FUNCTION phase3_target_hash();

CREATE FUNCTION phase3_sample_insert() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; era forecasts_experimentera%ROWTYPE; method forecasts_forecastmethodidentity%ROWTYPE; target forecasts_targetoccurrence%ROWTYPE;
BEGIN
 SELECT * INTO STRICT era FROM forecasts_experimentera WHERE id=NEW.era_id;
 SELECT * INTO STRICT method FROM forecasts_forecastmethodidentity WHERE id=era.method_id;
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF method.contract_version<>4 AND rec.contract_version<>4 THEN RETURN NEW; END IF;
 IF method.contract_version<>4 OR rec.contract_version<>4 OR rec.generated_at<era.starts_at OR NEW.assigned_at<rec.generated_at THEN RAISE EXCEPTION 'prospective_era_mismatch'; END IF;
 SELECT * INTO STRICT target FROM forecasts_targetoccurrence WHERE id=rec.target_occurrence_id;
 IF NEW.issuance_cluster_key<>target.identity_sha256 THEN RAISE EXCEPTION 'target_dependence_identity_mismatch'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_sample_validate BEFORE INSERT ON forecasts_experimentsample FOR EACH ROW EXECUTE FUNCTION phase3_sample_insert();

CREATE FUNCTION phase3_required_disposition() RETURNS trigger AS $$
BEGIN
 IF NEW.contract_version=4 THEN
  IF NOT EXISTS(SELECT 1 FROM forecasts_recommendationlifecycleevent WHERE recommendation_id=NEW.id)
  OR (NEW.action<>'abstain' AND NOT EXISTS(SELECT 1 FROM forecasts_portfoliodisposition WHERE recommendation_id=NEW.id))
  THEN RAISE EXCEPTION 'issuance_lifecycle_disposition_required'; END IF;
 END IF;
 RETURN NULL;
END; $$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER phase3_disposition_required AFTER INSERT ON forecasts_recommendation DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase3_required_disposition();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0019_phase3_integrity")]
    operations = [migrations.RunSQL(SQL)]
