from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_expired_result() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; maturity timestamptz;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF rec.contract_version<>4 OR NEW.outcome<>'expired' THEN RETURN NEW; END IF;
 SELECT ((phase3_endpoint(c.timestamp,t.horizon_sessions) AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 INTO maturity FROM forecasts_targetoccurrence t JOIN market_candle c ON c.id=t.reference_candle_id WHERE t.id=rec.target_occurrence_id;
 IF NEW.resolved_at<maturity OR NOT phase3_complete_hourly(rec.id,maturity,NEW.resolved_at)
 THEN RAISE EXCEPTION 'expiry_coverage_required'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_expired_result BEFORE INSERT ON forecasts_papertraderesult FOR EACH ROW EXECUTE FUNCTION phase3_expired_result();

CREATE FUNCTION phase3_revocation_semantics() RETURNS trigger AS $$
DECLARE version integer; current_state text;
BEGIN
 SELECT contract_version INTO STRICT version FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF version<>4 OR NEW.state<>'revoked' THEN RETURN NEW; END IF;
 SELECT state INTO current_state FROM forecasts_recommendationlifecycleevent WHERE recommendation_id=NEW.recommendation_id AND occurred_at<=NEW.occurred_at ORDER BY occurred_at DESC,id DESC LIMIT 1;
 IF current_state IS DISTINCT FROM 'admitted_awaiting_entry' OR EXISTS(SELECT 1 FROM forecasts_papertradeentry WHERE recommendation_id=NEW.recommendation_id AND entered_at<=NEW.occurred_at)
 THEN RAISE EXCEPTION 'revocation_requires_pending_admission'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_revocation_semantics BEFORE INSERT ON forecasts_portfolioadmissionevent FOR EACH ROW EXECUTE FUNCTION phase3_revocation_semantics();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0029_phase3_method_dependence")]
    operations = [migrations.RunSQL(SQL)]
