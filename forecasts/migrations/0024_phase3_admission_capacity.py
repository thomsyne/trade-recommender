from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_admission_guard() RETURNS trigger AS $$
DECLARE version integer; chosen forecasts_portfolioselection%ROWTYPE;
BEGIN
 SELECT contract_version INTO STRICT version FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF version<>4 THEN RETURN NEW; END IF;
 PERFORM key FROM forecasts_portfolioguard WHERE key='paper-portfolio' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'portfolio_guard_required'; END IF;
 SELECT * INTO STRICT chosen FROM forecasts_portfolioselection WHERE id=NEW.selection_id;
 IF NEW.occurred_at<chosen.selected_at OR chosen.id<>(SELECT id FROM forecasts_portfolioselection WHERE cohort_id=NEW.cohort_id ORDER BY selected_at DESC,id DESC LIMIT 1)
 THEN RAISE EXCEPTION 'current_selection_required'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_admission_guard BEFORE INSERT ON forecasts_portfolioadmissionevent FOR EACH ROW EXECUTE FUNCTION phase3_admission_guard();

CREATE FUNCTION phase3_admission_capacity() RETURNS trigger AS $$
DECLARE version integer; total numeric; largest numeric;
BEGIN
 SELECT contract_version INTO STRICT version FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF version<>4 OR NEW.state<>'admitted' THEN RETURN NULL; END IF;
 WITH latest AS (
  SELECT DISTINCT ON (recommendation_id) recommendation_id,state FROM forecasts_portfolioadmissionevent
  WHERE occurred_at<=NEW.occurred_at ORDER BY recommendation_id,occurred_at DESC,id DESC
 ), active AS (
  SELECT m.projected_risk_cad,m.currency_legs FROM latest a
  JOIN forecasts_recommendation r ON r.id=a.recommendation_id
  JOIN forecasts_portfoliocohortmember m ON m.recommendation_id=r.id
  WHERE a.state='admitted'
  AND NOT EXISTS(SELECT 1 FROM forecasts_papertraderesult WHERE recommendation_id=r.id AND resolved_at<=NEW.occurred_at)
  AND COALESCE((SELECT state FROM forecasts_recommendationlifecycleevent WHERE recommendation_id=r.id AND occurred_at<=NEW.occurred_at ORDER BY occurred_at DESC,id DESC LIMIT 1),'legacy_unadjudicated')
   NOT IN ('abstained','portfolio_ineligible','closed_unselected','admission_revoked','target_hit','invalidated','expired_after_entry','expired_not_activated','expired_unobserved','missing_data','cancelled')
 ), legs AS (
  SELECT leg->>'currency' currency,leg->>'direction' direction,sum(projected_risk_cad) risk
  FROM active CROSS JOIN LATERAL jsonb_array_elements(currency_legs) leg GROUP BY 1,2
 ) SELECT (SELECT COALESCE(sum(projected_risk_cad),0) FROM active),(SELECT COALESCE(max(risk),0) FROM legs) INTO total,largest;
 IF total>500 OR largest>250 THEN RAISE EXCEPTION 'current_capacity_exceeded'; END IF;
 RETURN NULL;
END; $$ LANGUAGE plpgsql;
CREATE CONSTRAINT TRIGGER phase3_admission_capacity AFTER INSERT ON forecasts_portfolioadmissionevent DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase3_admission_capacity();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0023_phase3_lifecycle_sources")]
    operations = [migrations.RunSQL(SQL)]
