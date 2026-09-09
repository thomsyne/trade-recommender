"""Prospective invariants only; existing immutable evidence is never rewritten."""

from django.db import migrations

TABLES = (
    "targetoccurrence",
    "targetresolution",
    "recommendationlifecycleevent",
    "portfoliodisposition",
    "cohortclosure",
)
SQL = r"""
CREATE FUNCTION phase3_endpoint(reference timestamptz, horizon integer) RETURNS timestamptz AS $$
DECLARE value timestamp := reference AT TIME ZONE 'America/New_York'; i integer;
BEGIN
 IF horizon < 1 OR horizon > 100 THEN RAISE EXCEPTION 'invalid_target_horizon'; END IF;
 FOR i IN 1..horizon LOOP
  value := value + CASE WHEN extract(isodow FROM value)=4 THEN interval '3 days' ELSE interval '1 day' END;
 END LOOP;
 RETURN value AT TIME ZONE 'America/New_York';
END; $$ LANGUAGE plpgsql IMMUTABLE;

CREATE FUNCTION phase3_target_insert() RETURNS trigger AS $$
DECLARE c market_candle%ROWTYPE; tc forecasts_targetcontract%ROWTYPE;
BEGIN
 SELECT * INTO STRICT c FROM market_candle WHERE id=NEW.reference_candle_id;
 SELECT * INTO STRICT tc FROM forecasts_targetcontract WHERE id=NEW.target_contract_id;
 IF c.instrument_id<>NEW.instrument_id OR c.granularity<>'D' OR NOT c.complete
 OR c.content_sha256<>NEW.reference_content_sha256
 OR NEW.reference_midpoint<>(c.bid_close+c.ask_close)/2
 OR NEW.horizon_sessions<>tc.horizon_sessions OR NEW.neutral_band<0
 OR NEW.registered_at<NEW.information_cutoff
 OR NEW.information_cutoff<((c.timestamp AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
 OR NEW.resolution_method<>'registered-session-endpoint-v2'
 OR NEW.neutral_rule<>'absolute-change-less-or-equal-band-v1'
 THEN RAISE EXCEPTION 'invalid_target_identity'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_target_validate BEFORE INSERT ON forecasts_targetoccurrence FOR EACH ROW EXECUTE FUNCTION phase3_target_insert();

CREATE UNIQUE INDEX phase3_one_control_method ON forecasts_forecast(target_occurrence_id, method, method_version) WHERE target_occurrence_id IS NOT NULL;
CREATE FUNCTION phase3_prediction_insert() RETURNS trigger AS $$
DECLARE t forecasts_targetoccurrence%ROWTYPE; f forecasts_forecast%ROWTYPE; e forecasts_evidencesnapshot%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='forecasts_recommendation' THEN
  IF NEW.contract_version<>4 THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='forecasts_forecast' AND NEW.target_occurrence_id IS NULL THEN RETURN NEW; END IF;
 IF NEW.target_occurrence_id IS NULL THEN RAISE EXCEPTION 'target_required'; END IF;
 SELECT * INTO STRICT t FROM forecasts_targetoccurrence WHERE id=NEW.target_occurrence_id;
 IF NEW.instrument_id<>t.instrument_id OR NEW.reference_midpoint<>t.reference_midpoint
 OR NEW.neutral_band<>t.neutral_band OR NEW.information_cutoff<>t.information_cutoff
 THEN RAISE EXCEPTION 'prediction_target_mismatch'; END IF;
 IF TG_TABLE_NAME='forecasts_recommendation' THEN
  IF NEW.control_forecast_id IS NULL THEN RAISE EXCEPTION 'exact_control_required'; END IF;
  SELECT * INTO STRICT f FROM forecasts_forecast WHERE id=NEW.control_forecast_id;
  IF f.target_occurrence_id IS DISTINCT FROM t.id OR f.issued_at>NEW.generated_at
  OR NEW.reference_candle_id<>t.reference_candle_id OR NEW.expires_after_sessions<>t.horizon_sessions
  OR f.method NOT IN ('mechanical-ewma','fixture-mechanical-ewma') OR f.method_version<>1
  THEN RAISE EXCEPTION 'exact_prospective_control_required'; END IF;
 ELSE
  SELECT * INTO STRICT e FROM forecasts_evidencesnapshot WHERE id=NEW.evidence_snapshot_id;
  IF NEW.target_contract_id<>t.target_contract_id OR NEW.setup_expires_after_sessions<>t.horizon_sessions
  OR e.anchor_candle_id<>t.reference_candle_id OR e.market_data_cutoff>t.information_cutoff
  OR NEW.issued_at<t.registered_at THEN RAISE EXCEPTION 'control_target_mismatch'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_forecast_validate BEFORE INSERT ON forecasts_forecast FOR EACH ROW EXECUTE FUNCTION phase3_prediction_insert();
CREATE TRIGGER phase3_recommendation_validate BEFORE INSERT ON forecasts_recommendation FOR EACH ROW EXECUTE FUNCTION phase3_prediction_insert();

CREATE FUNCTION phase3_resolution_insert() RETURNS trigger AS $$
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
  OR NEW.horizon_content_sha256<>c.content_sha256 OR NEW.endpoint_midpoint<>(c.bid_close+c.ask_close)/2
  OR NEW.midpoint_change<>NEW.endpoint_midpoint-t.reference_midpoint OR NEW.outcome<>classification
  OR NEW.resolved_at<((expected AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York'
  THEN RAISE EXCEPTION 'shared_endpoint_mismatch'; END IF;
 ELSIF NEW.outcome IN ('missing','cancelled') THEN
  IF NEW.horizon_candle_id IS NOT NULL OR NEW.endpoint_midpoint IS NOT NULL OR NEW.midpoint_change IS NOT NULL OR NEW.horizon_content_sha256<>'' THEN RAISE EXCEPTION 'unscored_endpoint_forbidden'; END IF;
  IF NEW.outcome='missing' AND NEW.resolved_at<((expected AT TIME ZONE 'America/New_York')+interval '1 day') AT TIME ZONE 'America/New_York' THEN RAISE EXCEPTION 'immature_missing_forbidden'; END IF;
 ELSE RAISE EXCEPTION 'invalid_target_outcome'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_resolution_validate BEFORE INSERT ON forecasts_targetresolution FOR EACH ROW EXECUTE FUNCTION phase3_resolution_insert();

CREATE FUNCTION phase3_derived_resolution() RETURNS trigger AS $$
DECLARE target_id bigint; r forecasts_targetresolution%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='forecasts_forecastresolution' THEN SELECT target_occurrence_id INTO target_id FROM forecasts_forecast WHERE id=NEW.forecast_id;
 ELSE SELECT target_occurrence_id INTO target_id FROM forecasts_recommendation WHERE id=NEW.recommendation_id; END IF;
 IF target_id IS NULL THEN RETURN NEW; END IF;
 IF NEW.target_resolution_id IS NULL THEN RAISE EXCEPTION 'shared_resolution_required'; END IF;
 SELECT * INTO STRICT r FROM forecasts_targetresolution WHERE id=NEW.target_resolution_id;
 IF r.target_id<>target_id OR NEW.outcome<>r.outcome OR NEW.horizon_candle_id IS DISTINCT FROM r.horizon_candle_id
 OR NEW.endpoint_midpoint IS DISTINCT FROM r.endpoint_midpoint OR NEW.midpoint_change IS DISTINCT FROM r.midpoint_change
 OR NEW.resolved_at<r.resolved_at THEN RAISE EXCEPTION 'derived_resolution_mismatch'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_forecast_resolution BEFORE INSERT ON forecasts_forecastresolution FOR EACH ROW EXECUTE FUNCTION phase3_derived_resolution();
CREATE TRIGGER phase3_recommendation_resolution BEFORE INSERT ON forecasts_recommendationresolution FOR EACH ROW EXECUTE FUNCTION phase3_derived_resolution();

CREATE FUNCTION phase3_lifecycle_insert() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; prior forecasts_recommendationlifecycleevent%ROWTYPE; allowed text[];
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id FOR UPDATE;
 IF rec.contract_version<>4 OR NEW.occurred_at<rec.generated_at OR NEW.details<> '{"schema_version":1}'::jsonb THEN RAISE EXCEPTION 'invalid_lifecycle_evidence'; END IF;
 SELECT * INTO prior FROM forecasts_recommendationlifecycleevent WHERE recommendation_id=rec.id ORDER BY occurred_at DESC,id DESC LIMIT 1;
 IF prior.id IS NULL THEN
  IF NEW.predecessor_id IS NOT NULL OR NEW.state<>(CASE WHEN rec.action='abstain' THEN 'abstained' ELSE 'awaiting_portfolio_assessment' END) THEN RAISE EXCEPTION 'invalid_lifecycle_root'; END IF;
 ELSE
  IF NEW.predecessor_id IS DISTINCT FROM prior.id OR NEW.occurred_at<prior.occurred_at THEN RAISE EXCEPTION 'conflicting_lifecycle_chain'; END IF;
  allowed:=CASE prior.state
    WHEN 'awaiting_portfolio_assessment' THEN ARRAY['portfolio_ineligible','awaiting_owner_decision','cancelled']
    WHEN 'awaiting_owner_decision' THEN ARRAY['admitted_awaiting_entry','closed_unselected','cancelled']
    WHEN 'admitted_awaiting_entry' THEN ARRAY['entered','admission_revoked','expired_not_activated','expired_unobserved','missing_data','cancelled']
    WHEN 'entered' THEN ARRAY['target_hit','invalidated','expired_after_entry','missing_data']
    ELSE ARRAY[]::text[] END;
  IF NOT NEW.state=ANY(allowed) THEN RAISE EXCEPTION 'illegal_lifecycle_transition'; END IF;
 END IF;
 IF NEW.state='awaiting_owner_decision' AND NOT EXISTS(SELECT 1 FROM forecasts_portfoliocohortmember WHERE recommendation_id=rec.id AND id=NEW.source_id) THEN RAISE EXCEPTION 'membership_required'; END IF;
 IF NEW.state='admitted_awaiting_entry' AND NOT EXISTS(SELECT 1 FROM forecasts_portfolioadmissionevent WHERE recommendation_id=rec.id AND id=NEW.source_id AND state='admitted' AND occurred_at<=NEW.occurred_at) THEN RAISE EXCEPTION 'admission_required'; END IF;
 IF NEW.state='entered' AND NOT EXISTS(SELECT 1 FROM forecasts_papertradeentry WHERE recommendation_id=rec.id AND id=NEW.source_id AND entered_at<=NEW.occurred_at) THEN RAISE EXCEPTION 'entry_required'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_lifecycle_validate BEFORE INSERT ON forecasts_recommendationlifecycleevent FOR EACH ROW EXECUTE FUNCTION phase3_lifecycle_insert();

CREATE FUNCTION phase3_execution_insert() RETURNS trigger AS $$
DECLARE rec forecasts_recommendation%ROWTYPE; admission forecasts_portfolioadmissionevent%ROWTYPE;
BEGIN
 SELECT * INTO STRICT rec FROM forecasts_recommendation WHERE id=NEW.recommendation_id FOR UPDATE;
 IF rec.contract_version<>4 THEN RETURN NEW; END IF;
 IF rec.action='abstain' THEN RAISE EXCEPTION 'abstention_execution_forbidden'; END IF;
 IF TG_TABLE_NAME='forecasts_portfoliocohortmember' THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='forecasts_portfolioselectionmember' THEN
  IF NOT EXISTS(SELECT 1 FROM forecasts_portfoliocohortmember m JOIN forecasts_portfolioselection s ON s.cohort_id=m.cohort_id WHERE s.id=NEW.selection_id AND m.recommendation_id=rec.id) THEN RAISE EXCEPTION 'selection_membership_required'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='forecasts_portfolioadmissionevent' THEN
  IF NOT EXISTS(SELECT 1 FROM forecasts_portfolioselection s JOIN forecasts_portfoliocohortmember m ON m.cohort_id=s.cohort_id WHERE s.id=NEW.selection_id AND s.cohort_id=NEW.cohort_id AND m.recommendation_id=rec.id)
  OR (NEW.state='admitted' AND NOT EXISTS(SELECT 1 FROM forecasts_portfolioselectionmember WHERE selection_id=NEW.selection_id AND recommendation_id=rec.id)) THEN RAISE EXCEPTION 'admission_selection_required'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO admission FROM forecasts_portfolioadmissionevent WHERE recommendation_id=rec.id ORDER BY occurred_at DESC,id DESC LIMIT 1;
 IF admission.id IS NULL OR admission.state<>'admitted' THEN RAISE EXCEPTION 'active_admission_required'; END IF;
 IF TG_TABLE_NAME='forecasts_papertraderesult' THEN
 IF NEW.outcome<>'not_activated' AND NOT EXISTS(SELECT 1 FROM forecasts_papertradeentry WHERE recommendation_id=rec.id AND id=NEW.entry_id) THEN RAISE EXCEPTION 'result_entry_required'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        raise RuntimeError("Phase3 requires PostgreSQL invariants")
    # No migration-generated prospective rows: installation fails before triggers if contradicted.
    if apps.get_model("forecasts", "Recommendation").objects.filter(contract_version=4).exists():
        raise RuntimeError(
            "Phase3 preflight: prospective rows require explicit validation before installation"
        )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(SQL)
        for table in TABLES:
            name = "forecasts_" + table
            cursor.execute(
                f"""CREATE FUNCTION phase3_immutable_{table}() RETURNS trigger AS $$
                BEGIN
                  -- Existing repository test-flush boundary; ordinary TRUNCATE still rejects.
                  IF TG_OP='TRUNCATE' AND current_database() LIKE 'test\\_%%' ESCAPE '\\'
                  AND EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND granted
                  AND mode='AccessExclusiveLock' AND relation='auth_permission'::regclass)
                  THEN RETURN NULL; END IF;
                  RAISE EXCEPTION 'governed_record_immutable';
                END; $$ LANGUAGE plpgsql"""
            )
            cursor.execute(
                f"CREATE TRIGGER phase3_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION phase3_immutable_{table}()"
            )
            cursor.execute(
                f"CREATE TRIGGER phase3_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION phase3_immutable_{table}()"
            )
        for table in (
            "portfoliocohortmember",
            "portfolioselectionmember",
            "portfolioadmissionevent",
            "papertradeentry",
            "papertraderesult",
        ):
            cursor.execute(
                f"CREATE TRIGGER phase3_execution_validate BEFORE INSERT ON forecasts_{table} FOR EACH ROW EXECUTE FUNCTION phase3_execution_insert()"
            )


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0018_portfoliocohort_decision_deadline_and_more")]
    operations = [migrations.RunPython(install)]
