from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION phase3_sample_insert() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; era forecasts_experimentera%ROWTYPE; method forecasts_forecastmethodidentity%ROWTYPE; target forecasts_targetoccurrence%ROWTYPE;
BEGIN
 SELECT * INTO STRICT era FROM forecasts_experimentera WHERE id=NEW.era_id;
 SELECT * INTO STRICT method FROM forecasts_forecastmethodidentity WHERE id=era.method_id;
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF method.contract_version<>4 AND rec.contract_version<>4 THEN RETURN NEW; END IF;
 IF method.contract_version<>4 OR rec.contract_version<>4 OR rec.provider<>method.provider OR rec.model<>method.requested_model OR rec.generated_at<era.starts_at OR NEW.assigned_at<rec.generated_at THEN RAISE EXCEPTION 'prospective_era_mismatch'; END IF;
 SELECT * INTO STRICT target FROM forecasts_targetoccurrence WHERE id=rec.target_occurrence_id;
 IF NEW.issuance_cluster_key<>target.identity_sha256 OR NEW.dependence_cluster_key<>(SELECT to_char(timestamp AT TIME ZONE 'UTC','IYYY-"W"IW') FROM market_candle WHERE id=target.reference_candle_id) THEN RAISE EXCEPTION 'target_dependence_identity_mismatch'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE FUNCTION phase3_control_method() RETURNS trigger AS $$
BEGIN
 IF NEW.target_occurrence_id IS NOT NULL AND (NEW.method NOT IN ('mechanical-ewma','fixture-mechanical-ewma') OR NEW.method_version<>1)
 THEN RAISE EXCEPTION 'control_target_mismatch'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_control_method BEFORE INSERT ON forecasts_forecast FOR EACH ROW EXECUTE FUNCTION phase3_control_method();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0028_phase3_semantic_coverage")]
    operations = [migrations.RunSQL(SQL)]
