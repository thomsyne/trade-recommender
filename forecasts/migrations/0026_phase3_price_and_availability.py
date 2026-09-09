from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_price(v numeric) RETURNS numeric AS $$
 SELECT CASE WHEN abs(v*1000000-trunc(v*1000000))=.5 AND mod(abs(trunc(v*1000000)),2)=0
 THEN trunc(v*1000000)/1000000 ELSE round(v,6) END;
$$ LANGUAGE sql IMMUTABLE STRICT;
CREATE OR REPLACE FUNCTION phase3_target_insert() RETURNS trigger AS $$
DECLARE c market_candle%ROWTYPE; tc forecasts_targetcontract%ROWTYPE;
BEGIN
 SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.reference_candle_id;
 SELECT * INTO STRICT tc FROM forecasts_targetcontract WHERE id=NEW.target_contract_id;
 IF c.instrument_id<>NEW.instrument_id OR c.granularity<>'D' OR NOT c.complete
 OR c.content_sha256<>NEW.reference_content_sha256
 OR NEW.reference_midpoint<>phase3_price((c.bid_close+c.ask_close)/2)
 OR NEW.horizon_sessions<>tc.horizon_sessions OR NEW.neutral_band<0
 OR NEW.registered_at<NEW.information_cutoff
 OR NEW.information_cutoff<((c.timestamp AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 OR NEW.resolution_method<>'registered-session-endpoint-v2'
 OR NEW.neutral_rule<>'absolute-change-less-or-equal-band-v1'
 THEN RAISE EXCEPTION 'invalid_target_identity'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION phase3_resolution_insert() RETURNS trigger AS $$
DECLARE t forecasts_targetoccurrence%ROWTYPE; c market_candle%ROWTYPE; expected timestamptz; classification text;
BEGIN
 SELECT * INTO STRICT t FROM forecasts_targetoccurrence WHERE id=NEW.target_id;
 expected:=phase3_endpoint((SELECT timestamp FROM market_candle WHERE id=t.reference_candle_id),t.horizon_sessions);
 IF NEW.resolution_method<>t.resolution_method OR NEW.resolved_at<t.registered_at THEN RAISE EXCEPTION 'resolution_contract_mismatch'; END IF;
 IF NEW.outcome IN ('up','neutral','down') THEN
  IF NEW.horizon_candle_id IS NULL OR NEW.endpoint_midpoint IS NULL OR NEW.midpoint_change IS NULL THEN RAISE EXCEPTION 'scored_endpoint_required'; END IF;
  SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.horizon_candle_id;
  classification:=CASE WHEN NEW.midpoint_change>t.neutral_band THEN 'up' WHEN NEW.midpoint_change< -t.neutral_band THEN 'down' ELSE 'neutral' END;
  IF c.timestamp<>expected OR c.instrument_id<>t.instrument_id OR c.granularity<>'D' OR NOT c.complete
  OR NOT EXISTS(SELECT 1 FROM market_ingestionrun r WHERE r.id=c.ingestion_run_id AND r.status='succeeded' AND r.finished_at<=NEW.resolved_at)
  OR NEW.horizon_content_sha256<>c.content_sha256 OR NEW.endpoint_midpoint<>phase3_price((c.bid_close+c.ask_close)/2)
  OR NEW.midpoint_change<>NEW.endpoint_midpoint-t.reference_midpoint OR NEW.outcome<>classification
  OR NEW.resolved_at<((expected AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
  THEN RAISE EXCEPTION 'shared_endpoint_mismatch'; END IF;
 ELSIF NEW.outcome IN ('missing','cancelled') THEN
  IF NEW.horizon_candle_id IS NOT NULL OR NEW.endpoint_midpoint IS NOT NULL OR NEW.midpoint_change IS NOT NULL OR NEW.horizon_content_sha256<>'' THEN RAISE EXCEPTION 'unscored_endpoint_forbidden'; END IF;
  IF NEW.outcome='missing' AND NEW.resolved_at<((expected AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York' THEN RAISE EXCEPTION 'immature_missing_forbidden'; END IF;
 ELSE RAISE EXCEPTION 'invalid_target_outcome'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0025_phase3_execution_evidence")]
    operations = [migrations.RunSQL(SQL)]
