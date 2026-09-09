from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_execution_evidence() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; c market_candle%ROWTYPE; observed timestamptz; horizon timestamptz;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF rec.contract_version<>4 THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='forecasts_papertradeentry' THEN
  SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.candle_id;
  SELECT finished_at INTO observed FROM market_ingestionrun WHERE id=c.ingestion_run_id AND status='succeeded';
  IF c.instrument_id<>rec.instrument_id OR c.granularity<>'H1' OR NOT c.complete OR c.timestamp<rec.generated_at
  OR observed IS NULL OR observed>NEW.entered_at OR c.timestamp+interval '1 hour'>NEW.entered_at
  OR NEW.execution_side<>(CASE WHEN rec.action='buy' THEN 'ask' ELSE 'bid' END)
  OR NEW.observed_open_spread<>c.ask_open-c.bid_open OR NEW.fill_price<=0
  OR NEW.details->>'candle_content_sha256' IS DISTINCT FROM c.content_sha256
  THEN RAISE EXCEPTION 'entry_evidence_mismatch'; END IF;
 ELSE
  IF NEW.entry_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM forecasts_papertradeentry WHERE id=NEW.entry_id AND recommendation_id=rec.id AND entered_at<=NEW.resolved_at)
  THEN RAISE EXCEPTION 'result_entry_evidence_mismatch'; END IF;
  IF NEW.horizon_candle_id IS NOT NULL THEN
   SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.horizon_candle_id;
   SELECT phase3_endpoint(reference.timestamp,t.horizon_sessions) INTO horizon FROM forecasts_targetoccurrence t JOIN market_candle reference ON reference.id=t.reference_candle_id WHERE t.id=rec.target_occurrence_id;
   IF c.instrument_id<>rec.instrument_id OR c.granularity<>'D' OR c.timestamp<>horizon OR NOT c.complete THEN RAISE EXCEPTION 'paper_endpoint_mismatch'; END IF;
  END IF;
  IF NEW.exit_candle_id IS NOT NULL THEN
   SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.exit_candle_id;
   SELECT finished_at INTO observed FROM market_ingestionrun WHERE id=c.ingestion_run_id AND status='succeeded';
   IF c.instrument_id<>rec.instrument_id OR NOT c.complete OR observed IS NULL OR observed>NEW.resolved_at OR c.timestamp<rec.generated_at
   THEN RAISE EXCEPTION 'exit_evidence_mismatch'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_entry_evidence BEFORE INSERT ON forecasts_papertradeentry FOR EACH ROW EXECUTE FUNCTION phase3_execution_evidence();
CREATE TRIGGER phase3_exit_evidence BEFORE INSERT ON forecasts_papertraderesult FOR EACH ROW EXECUTE FUNCTION phase3_execution_evidence();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0024_phase3_admission_capacity")]
    operations = [migrations.RunSQL(SQL)]
