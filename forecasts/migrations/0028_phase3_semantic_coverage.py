from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_complete_hourly(rec_id bigint, through_at timestamptz, available_at timestamptz) RETURNS boolean AS $$
 WITH rec AS (SELECT * FROM forecasts_recommendation WHERE id=rec_id), expected AS (
 SELECT hour FROM rec, generate_series(date_trunc('hour',rec.generated_at)+interval '1 hour',through_at-interval '1 hour',interval '1 hour') hour
 WHERE extract(isodow FROM hour AT TIME ZONE 'America/New_York') BETWEEN 1 AND 4
 OR (extract(isodow FROM hour AT TIME ZONE 'America/New_York')=5 AND extract(hour FROM hour AT TIME ZONE 'America/New_York')<17)
 OR (extract(isodow FROM hour AT TIME ZONE 'America/New_York')=7 AND extract(hour FROM hour AT TIME ZONE 'America/New_York')>=17)
 )
 SELECT EXISTS(SELECT 1 FROM expected) AND EXISTS(
 SELECT 1 FROM market_ingestionrun r, rec WHERE r.instrument_id=rec.instrument_id AND r.granularity='H1' AND r.status='succeeded'
 AND r.finished_at<=available_at AND r.requested_from<=rec.generated_at AND r.requested_to>=through_at)
 AND NOT EXISTS(SELECT 1 FROM expected,rec WHERE NOT EXISTS(
 SELECT 1 FROM market_candle c JOIN market_ingestionrun r ON r.id=c.ingestion_run_id
 WHERE c.instrument_id=rec.instrument_id AND c.granularity='H1' AND c.timestamp=expected.hour AND c.complete
 AND r.status='succeeded' AND r.finished_at<=available_at AND c.timestamp+interval '1 hour'<=available_at));
$$ LANGUAGE sql STABLE;

CREATE FUNCTION phase3_assert_coverage(rec_id bigint, fact_state text, reason text, evidence jsonb, at_time timestamptz) RETURNS void AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; maturity timestamptz; entered boolean;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=rec_id;
 IF rec.contract_version<>4 THEN RETURN; END IF;
 IF jsonb_typeof(evidence)<>'object' OR evidence->'schema_version' IS DISTINCT FROM '1'::jsonb THEN RAISE EXCEPTION 'invalid_coverage_details'; END IF;
 entered:=EXISTS(SELECT 1 FROM forecasts_papertradeentry WHERE recommendation_id=rec.id AND entered_at<=at_time);
 IF fact_state='cancelled' THEN
  IF entered OR reason='' OR at_time<rec.generated_at THEN RAISE EXCEPTION 'invalid_cancellation_evidence'; END IF;
  RETURN;
 END IF;
 IF fact_state NOT IN ('expired_unobserved','missing_data') THEN RETURN; END IF;
 SELECT ((phase3_endpoint(c.timestamp,t.horizon_sessions) AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 INTO maturity FROM forecasts_targetoccurrence t JOIN market_candle c ON c.id=t.reference_candle_id WHERE t.id=rec.target_occurrence_id;
 IF at_time<maturity THEN RAISE EXCEPTION 'coverage_before_target_maturity'; END IF;
 IF reason='daily_horizon_unavailable' THEN
  IF fact_state<>'missing_data' OR NOT EXISTS(SELECT 1 FROM forecasts_targetresolution r WHERE r.target_id=rec.target_occurrence_id AND r.outcome='missing' AND r.resolved_at<=at_time AND to_jsonb(r.id)=evidence->'target_resolution_id')
  THEN RAISE EXCEPTION 'missing_daily_source_required'; END IF;
 ELSIF reason='hourly_coverage_unavailable' THEN
  IF fact_state<>(CASE WHEN entered THEN 'missing_data' ELSE 'expired_unobserved' END)
  OR phase3_complete_hourly(rec.id,maturity,at_time) THEN RAISE EXCEPTION 'coverage_classification_mismatch'; END IF;
 ELSE RAISE EXCEPTION 'invalid_coverage_reason'; END IF;
 RETURN;
END; $$ LANGUAGE plpgsql;
CREATE FUNCTION phase3_coverage_semantics() RETURNS trigger AS $$
BEGIN
 PERFORM phase3_assert_coverage(NEW.recommendation_id,NEW.state,NEW.reason_code,NEW.details,NEW.occurred_at);
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE FUNCTION phase3_transition_coverage() RETURNS trigger AS $$
DECLARE fact forecasts_paperlifecycleevent%ROWTYPE;
BEGIN
 IF NEW.state IN ('expired_unobserved','missing_data','cancelled') THEN
  IF NEW.source_type<>'PaperLifecycleEvent' THEN RAISE EXCEPTION 'coverage_source_required'; END IF;
  SELECT * INTO STRICT fact FROM forecasts_paperlifecycleevent WHERE id=NEW.source_id;
  IF fact.recommendation_id<>NEW.recommendation_id OR fact.state<>NEW.state OR fact.occurred_at>NEW.occurred_at THEN RAISE EXCEPTION 'coverage_source_mismatch'; END IF;
  PERFORM phase3_assert_coverage(fact.recommendation_id,fact.state,fact.reason_code,fact.details,fact.occurred_at);
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_transition_coverage BEFORE INSERT ON forecasts_recommendationlifecycleevent FOR EACH ROW EXECUTE FUNCTION phase3_transition_coverage();
CREATE TRIGGER phase3_coverage_semantics BEFORE INSERT ON forecasts_paperlifecycleevent FOR EACH ROW EXECUTE FUNCTION phase3_coverage_semantics();

CREATE FUNCTION phase3_nonactivation_semantics() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; maturity timestamptz;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF rec.contract_version<>4 OR NEW.outcome<>'not_activated' THEN RETURN NEW; END IF;
 SELECT ((phase3_endpoint(c.timestamp,t.horizon_sessions) AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 INTO maturity FROM forecasts_targetoccurrence t JOIN market_candle c ON c.id=t.reference_candle_id WHERE t.id=rec.target_occurrence_id;
 IF NEW.resolved_at<maturity OR NEW.entry_id IS NOT NULL OR EXISTS(SELECT 1 FROM forecasts_papertradeentry WHERE recommendation_id=rec.id)
 OR NOT phase3_complete_hourly(rec.id,maturity,NEW.resolved_at)
 THEN RAISE EXCEPTION 'nonactivation_coverage_required'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_nonactivation_semantics BEFORE INSERT ON forecasts_papertraderesult FOR EACH ROW EXECUTE FUNCTION phase3_nonactivation_semantics();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0027_phase3_trusted_issuance")]
    operations = [migrations.RunSQL(SQL)]
