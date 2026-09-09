from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_control_evidence() RETURNS trigger AS $$
DECLARE e forecasts_evidencesnapshot%ROWTYPE; tech market_technicalsnapshot%ROWTYPE; r market_ingestionrun%ROWTYPE;
BEGIN
 IF NEW.target_occurrence_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO STRICT e FROM forecasts_evidencesnapshot WHERE id=NEW.evidence_snapshot_id;
 SELECT * INTO STRICT tech FROM market_technicalsnapshot WHERE id=e.technical_snapshot_id;
 SELECT run.* INTO STRICT r FROM market_ingestionrun run JOIN market_candle c ON c.ingestion_run_id=run.id WHERE c.id=e.anchor_candle_id;
 IF e.captured_at>NEW.issued_at OR tech.calculated_at>NEW.information_cutoff OR r.finished_at>NEW.information_cutoff
 OR tech.instrument_id<>NEW.instrument_id OR tech.granularity<>'D'
 OR NOT EXISTS(SELECT 1 FROM market_instrument WHERE id=NEW.instrument_id AND active AND code IN ('EUR_USD','GBP_USD','EUR_GBP','USD_CAD'))
 THEN RAISE EXCEPTION 'control_evidence_cutoff_or_instrument'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_control_evidence_validate BEFORE INSERT ON forecasts_forecast FOR EACH ROW EXECUTE FUNCTION phase3_control_evidence();

CREATE FUNCTION phase3_resolution_score() RETURNS trigger AS $$
DECLARE p_up numeric; p_neutral numeric; p_down numeric; action text; target bigint; score numeric;
BEGIN
 IF TG_TABLE_NAME='forecasts_forecastresolution' THEN
  SELECT target_occurrence_id,probability_up,probability_neutral,probability_down INTO target,p_up,p_neutral,p_down FROM forecasts_forecast WHERE id=NEW.forecast_id;
 ELSE
  SELECT target_occurrence_id,probability_up,probability_neutral,probability_down,r.action INTO target,p_up,p_neutral,p_down,action FROM forecasts_recommendation r WHERE id=NEW.recommendation_id;
 END IF;
 IF target IS NULL THEN RETURN NEW; END IF;
 IF NEW.outcome IN ('up','neutral','down') THEN
  score:=round(((p_up-(CASE WHEN NEW.outcome='up' THEN 1 ELSE 0 END))^2+(p_neutral-(CASE WHEN NEW.outcome='neutral' THEN 1 ELSE 0 END))^2+(p_down-(CASE WHEN NEW.outcome='down' THEN 1 ELSE 0 END))^2)/3,6);
  IF NEW.brier_score IS DISTINCT FROM score THEN RAISE EXCEPTION 'prediction_score_mismatch'; END IF;
  IF TG_TABLE_NAME='forecasts_recommendationresolution' THEN
   IF (action='abstain' AND NEW.directional_hit IS NOT NULL)
   OR (action<>'abstain' AND NEW.directional_hit IS DISTINCT FROM (NEW.outcome=CASE WHEN action='buy' THEN 'up' ELSE 'down' END)) THEN RAISE EXCEPTION 'directional_hit_mismatch'; END IF;
  END IF;
 ELSE
  IF NEW.brier_score IS NOT NULL THEN RAISE EXCEPTION 'unscored_brier_forbidden'; END IF;
  IF TG_TABLE_NAME='forecasts_recommendationresolution' THEN
   IF NEW.directional_hit IS NOT NULL THEN RAISE EXCEPTION 'unscored_hit_forbidden'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_forecast_score BEFORE INSERT ON forecasts_forecastresolution FOR EACH ROW EXECUTE FUNCTION phase3_resolution_score();
CREATE TRIGGER phase3_recommendation_score BEFORE INSERT ON forecasts_recommendationresolution FOR EACH ROW EXECUTE FUNCTION phase3_resolution_score();

CREATE FUNCTION phase3_lifecycle_source() RETURNS trigger AS $$
DECLARE outcome text; rec bigint; evidence_at timestamptz;
BEGIN
 IF NEW.state IN ('target_hit','invalidated','expired_after_entry','expired_not_activated') THEN
  IF NEW.source_type<>'PaperTradeResult' THEN RAISE EXCEPTION 'terminal_result_source_required'; END IF;
  SELECT recommendation_id,r.outcome,resolved_at INTO STRICT rec,outcome,evidence_at FROM forecasts_papertraderesult r WHERE id=NEW.source_id;
  IF rec<>NEW.recommendation_id OR evidence_at>NEW.occurred_at OR NEW.state<>(CASE outcome WHEN 'target' THEN 'target_hit' WHEN 'invalidated' THEN 'invalidated' WHEN 'expired' THEN 'expired_after_entry' WHEN 'not_activated' THEN 'expired_not_activated' ELSE '' END) THEN RAISE EXCEPTION 'terminal_result_source_mismatch'; END IF;
 ELSIF NEW.state IN ('missing_data','expired_unobserved','cancelled') THEN
  IF NEW.source_type<>'PaperLifecycleEvent' THEN RAISE EXCEPTION 'coverage_source_required'; END IF;
  IF NOT EXISTS(SELECT 1 FROM forecasts_paperlifecycleevent WHERE id=NEW.source_id AND recommendation_id=NEW.recommendation_id AND state=NEW.state AND occurred_at<=NEW.occurred_at) THEN RAISE EXCEPTION 'coverage_source_mismatch'; END IF;
 ELSIF NEW.state='entered' AND NEW.source_type<>'PaperTradeEntry' THEN RAISE EXCEPTION 'entry_source_required';
 ELSIF NEW.state='admitted_awaiting_entry' AND NEW.source_type<>'PortfolioAdmissionEvent' THEN RAISE EXCEPTION 'admission_source_required';
 ELSIF NEW.state='awaiting_owner_decision' AND NEW.source_type<>'PortfolioCohortMember' THEN RAISE EXCEPTION 'membership_source_required';
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_lifecycle_source_validate BEFORE INSERT ON forecasts_recommendationlifecycleevent FOR EACH ROW EXECUTE FUNCTION phase3_lifecycle_source();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0020_phase3_identity_hash")]
    operations = [migrations.RunSQL(SQL)]
