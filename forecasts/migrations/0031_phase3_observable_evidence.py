"""Reject new contradictory facts without rewriting immutable historical evidence."""

from django.db import migrations

SQL = r"""
-- Mirrors paper._entry_fill's inclusive, execution-side entry predicate.
CREATE FUNCTION phase3_observable_activation(rec_id bigint, available_at timestamptz) RETURNS boolean AS $$
 SELECT EXISTS(
 SELECT 1 FROM forecasts_recommendation rec
 JOIN forecasts_targetoccurrence t ON t.id=rec.target_occurrence_id
 JOIN market_candle reference ON reference.id=t.reference_candle_id
 JOIN market_candle c ON c.instrument_id=rec.instrument_id
 JOIN market_ingestionrun run ON run.id=c.ingestion_run_id
 WHERE rec.id=rec_id AND c.granularity='H1' AND c.complete
 AND c.timestamp>=rec.generated_at AND c.timestamp+interval '1 hour'<=available_at
 AND c.timestamp+interval '1 hour'<=((phase3_endpoint(reference.timestamp,t.horizon_sessions)
 AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 AND run.status='succeeded' AND run.finished_at<=available_at
 AND CASE WHEN rec.entry_condition='at_or_below'
 THEN (CASE WHEN rec.action='buy' THEN c.ask_low ELSE c.bid_low END)<=rec.entry_level
 ELSE (CASE WHEN rec.action='buy' THEN c.ask_high ELSE c.bid_high END)>=rec.entry_level END);
$$ LANGUAGE sql STABLE;

CREATE FUNCTION phase3_nonactivation_observation() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; cutoff timestamptz;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF rec.contract_version<>4 THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='forecasts_papertraderesult' THEN
  IF NEW.outcome<>'not_activated' THEN RETURN NEW; END IF;
  cutoff:=NEW.resolved_at;
 ELSE
  IF NEW.state<>'expired_not_activated' THEN RETURN NEW; END IF;
  SELECT resolved_at INTO cutoff FROM forecasts_papertraderesult
  WHERE id=NEW.source_id AND recommendation_id=rec.id AND outcome='not_activated';
 END IF;
 IF phase3_observable_activation(rec.id,cutoff)
 THEN RAISE EXCEPTION 'nonactivation_contradicts_entry_evidence'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_nonactivation_observation BEFORE INSERT ON forecasts_papertraderesult
FOR EACH ROW EXECUTE FUNCTION phase3_nonactivation_observation();
CREATE TRIGGER phase3_nonactivation_observation BEFORE INSERT ON forecasts_recommendationlifecycleevent
FOR EACH ROW EXECUTE FUNCTION phase3_nonactivation_observation();

CREATE FUNCTION phase3_missing_observation() RETURNS trigger AS $$
BEGIN
 IF NEW.outcome='missing' AND EXISTS(
 SELECT 1 FROM forecasts_targetoccurrence t
 JOIN market_candle reference ON reference.id=t.reference_candle_id
 JOIN market_candle c ON c.instrument_id=t.instrument_id
 JOIN market_ingestionrun run ON run.id=c.ingestion_run_id
 WHERE t.id=NEW.target_id AND c.granularity='D' AND c.complete
 AND c.timestamp=phase3_endpoint(reference.timestamp,t.horizon_sessions)
 AND ((c.timestamp AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'<=NEW.resolved_at
 AND run.status='succeeded' AND run.finished_at<=NEW.resolved_at)
 THEN RAISE EXCEPTION 'available_endpoint_marked_missing'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_z_missing_observation BEFORE INSERT ON forecasts_targetresolution
FOR EACH ROW EXECUTE FUNCTION phase3_missing_observation();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0030_phase3_terminal_semantics")]
    operations = [migrations.RunSQL(SQL)]
