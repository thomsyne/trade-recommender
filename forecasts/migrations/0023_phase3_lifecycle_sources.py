from django.db import migrations

SQL = r"""
CREATE FUNCTION phase3_final_state_source() RETURNS trigger AS $$
BEGIN
 IF NEW.state='closed_unselected' THEN
  IF NEW.source_type<>'CohortClosure' OR NOT EXISTS(
   SELECT 1 FROM forecasts_cohortclosure c JOIN forecasts_portfoliocohortmember m ON m.cohort_id=c.cohort_id
   WHERE c.id=NEW.source_id AND m.recommendation_id=NEW.recommendation_id AND c.closed_at<=NEW.occurred_at)
  THEN RAISE EXCEPTION 'closure_source_required'; END IF;
 ELSIF NEW.state='admission_revoked' THEN
  IF NEW.source_type<>'PortfolioAdmissionEvent' OR NOT EXISTS(
   SELECT 1 FROM forecasts_portfolioadmissionevent WHERE id=NEW.source_id AND recommendation_id=NEW.recommendation_id AND state='revoked' AND occurred_at<=NEW.occurred_at)
  THEN RAISE EXCEPTION 'revocation_source_required'; END IF;
 ELSIF NEW.state IN ('abstained','awaiting_portfolio_assessment','portfolio_ineligible') THEN
  IF NEW.source_type<>'Recommendation' OR NEW.source_id<>NEW.recommendation_id THEN RAISE EXCEPTION 'recommendation_source_required'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_final_state_source BEFORE INSERT ON forecasts_recommendationlifecycleevent FOR EACH ROW EXECUTE FUNCTION phase3_final_state_source();

CREATE FUNCTION phase3_disposition_source() RETURNS trigger AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM forecasts_recommendation WHERE id=NEW.recommendation_id AND contract_version=4 AND action<>'abstain' AND generated_at<=NEW.created_at)
 OR NEW.kind<>'requires_assessment' OR NEW.reason_code<>'assessment_required'
 THEN RAISE EXCEPTION 'invalid_initial_disposition'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_disposition_source BEFORE INSERT ON forecasts_portfoliodisposition FOR EACH ROW EXECUTE FUNCTION phase3_disposition_source();

CREATE FUNCTION phase3_member_evidence() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; c forecasts_portfoliocohort%ROWTYPE; size forecasts_positionsizeadvice%ROWTYPE; endpoint timestamptz;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id;
 IF rec.contract_version<>4 THEN RETURN NEW; END IF;
 SELECT * INTO STRICT c FROM forecasts_portfoliocohort WHERE id=NEW.cohort_id;
 SELECT * INTO STRICT size FROM forecasts_positionsizeadvice WHERE id=NEW.position_size_id;
 SELECT phase3_endpoint(candle.timestamp,t.horizon_sessions) INTO endpoint FROM forecasts_targetoccurrence t JOIN market_candle candle ON candle.id=t.reference_candle_id WHERE t.id=rec.target_occurrence_id;
 IF NOT NEW.eligible OR size.recommendation_id<>rec.id OR NEW.projected_risk_cad<>size.projected_risk_cad
 OR size.sized_at>c.generated_at OR c.generated_at<rec.generated_at OR c.decision_deadline IS NULL
 OR c.decision_deadline<=c.generated_at OR c.decision_deadline>rec.generated_at+interval '24 hours'
 OR c.decision_deadline>((endpoint AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 THEN RAISE EXCEPTION 'membership_evidence_mismatch'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_member_evidence BEFORE INSERT ON forecasts_portfoliocohortmember FOR EACH ROW EXECUTE FUNCTION phase3_member_evidence();

CREATE FUNCTION phase3_closure_evidence() RETURNS trigger AS $$
DECLARE c forecasts_portfoliocohort%ROWTYPE;
BEGIN
 SELECT * INTO STRICT c FROM forecasts_portfoliocohort WHERE id=NEW.cohort_id FOR UPDATE;
 IF c.decision_deadline IS NULL OR NEW.closed_at<c.generated_at THEN RAISE EXCEPTION 'invalid_cohort_closure'; END IF;
 IF NEW.reason_code='selection_recorded' AND NOT EXISTS(SELECT 1 FROM forecasts_portfolioselection WHERE cohort_id=c.id AND selected_at<=NEW.closed_at) THEN RAISE EXCEPTION 'closure_selection_required'; END IF;
 IF NEW.reason_code='decision_deadline' AND NEW.closed_at<c.decision_deadline THEN RAISE EXCEPTION 'premature_deadline_closure'; END IF;
 IF NEW.reason_code='new_target_superseded' AND NOT EXISTS(
  SELECT 1 FROM forecasts_portfoliocohort newer JOIN forecasts_portfoliocohortmember nm ON nm.cohort_id=newer.id
  JOIN forecasts_recommendation nr ON nr.id=nm.recommendation_id
  JOIN forecasts_portfoliocohortmember om ON om.cohort_id=c.id
  JOIN forecasts_recommendation older_rec ON older_rec.id=om.recommendation_id
  WHERE newer.id=NEW.superseding_cohort_id AND newer.generated_at>c.generated_at AND newer.generated_at<=NEW.closed_at
  AND nr.instrument_id=older_rec.instrument_id AND nr.target_occurrence_id IS DISTINCT FROM older_rec.target_occurrence_id)
 THEN RAISE EXCEPTION 'material_new_target_required'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_closure_evidence BEFORE INSERT ON forecasts_cohortclosure FOR EACH ROW EXECUTE FUNCTION phase3_closure_evidence();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0022_phase3_decision_boundaries")]
    operations = [migrations.RunSQL(SQL)]
