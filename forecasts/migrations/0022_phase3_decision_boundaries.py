"""Close direct-insert paths around prospective issuance and owner decisions."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_issuance_time() RETURNS trigger AS $$
DECLARE t forecasts_targetoccurrence%ROWTYPE; issued timestamptz; endpoint timestamptz;
BEGIN
 IF NEW.target_occurrence_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO STRICT t FROM forecasts_targetoccurrence WHERE id=NEW.target_occurrence_id;
 IF TG_TABLE_NAME='forecasts_recommendation' THEN issued:=NEW.generated_at;
 ELSE issued:=NEW.issued_at; END IF;
 endpoint:=phase3_endpoint((SELECT timestamp FROM market_candle WHERE id=t.reference_candle_id),t.horizon_sessions);
 IF issued<t.registered_at OR issued>=((endpoint AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 THEN RAISE EXCEPTION 'issuance_outside_target_window'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_issuance_window BEFORE INSERT ON forecasts_forecast FOR EACH ROW EXECUTE FUNCTION phase3_issuance_time();
CREATE TRIGGER phase3_issuance_window BEFORE INSERT ON forecasts_recommendation FOR EACH ROW EXECUTE FUNCTION phase3_issuance_time();

CREATE FUNCTION phase3_selection_time() RETURNS trigger AS $$
DECLARE c forecasts_portfoliocohort%ROWTYPE;
BEGIN
 SELECT * INTO STRICT c FROM forecasts_portfoliocohort WHERE id=NEW.cohort_id FOR UPDATE;
 IF c.decision_deadline IS NULL THEN RETURN NEW; END IF;
 IF NEW.selected_at<c.generated_at OR NEW.selected_at>=c.decision_deadline
 OR EXISTS(SELECT 1 FROM forecasts_cohortclosure WHERE cohort_id=c.id)
 OR EXISTS(SELECT 1 FROM forecasts_portfolioselection WHERE cohort_id=c.id)
 THEN RAISE EXCEPTION 'decision_window_closed'; END IF;
 IF EXISTS(SELECT 1 FROM forecasts_portfoliocohortmember m
 JOIN forecasts_recommendation r ON r.id=m.recommendation_id
 JOIN market_candle h ON h.instrument_id=r.instrument_id
 JOIN market_ingestionrun run ON run.id=h.ingestion_run_id
 WHERE m.cohort_id=c.id AND h.granularity='H1' AND h.complete
 AND h.timestamp>=r.generated_at AND h.timestamp+interval '1 hour'<=NEW.selected_at
 AND run.finished_at<=NEW.selected_at AND run.status='succeeded'
 AND ((r.action='buy' AND h.ask_low<=r.entry_level) OR (r.action='sell' AND h.bid_high>=r.entry_level)))
 THEN RAISE EXCEPTION 'decision_price_triggered'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_selection_window BEFORE INSERT ON forecasts_portfolioselection FOR EACH ROW EXECUTE FUNCTION phase3_selection_time();

CREATE FUNCTION phase3_entry_state() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; current_state text;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id FOR UPDATE;
 IF rec.contract_version<>4 THEN RETURN NEW; END IF;
 SELECT state INTO current_state FROM forecasts_recommendationlifecycleevent WHERE recommendation_id=rec.id ORDER BY occurred_at DESC,id DESC LIMIT 1;
 IF TG_TABLE_NAME='forecasts_papertradeentry' THEN
  IF current_state IS DISTINCT FROM 'admitted_awaiting_entry' THEN RAISE EXCEPTION 'entry_requires_live_admission_state'; END IF;
 ELSE
  IF NEW.outcome='not_activated' THEN
   IF current_state IS DISTINCT FROM 'admitted_awaiting_entry' THEN RAISE EXCEPTION 'unactivated_result_requires_admission'; END IF;
  ELSIF current_state IS DISTINCT FROM 'entered' THEN RAISE EXCEPTION 'result_requires_entered_state'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_entry_state BEFORE INSERT ON forecasts_papertradeentry FOR EACH ROW EXECUTE FUNCTION phase3_entry_state();
CREATE TRIGGER phase3_result_state BEFORE INSERT ON forecasts_papertraderesult FOR EACH ROW EXECUTE FUNCTION phase3_entry_state();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0021_phase3_evidence_boundaries")]
    operations = [migrations.RunSQL(SQL)]
