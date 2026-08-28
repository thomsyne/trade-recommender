from importlib import import_module

from django.db import migrations

HISTORICAL_DATASET_FUNCTION = """
CREATE OR REPLACE FUNCTION market_validate_historical_dataset() RETURNS trigger AS $$
DECLARE plan record; strategy record; expected_manifest jsonb; required_ranges jsonb;
BEGIN
  IF TG_OP='DELETE' THEN
    IF OLD.manifest ? 'historical_plan_sha256' THEN
      RAISE EXCEPTION 'historical dataset manifests are immutable';
    END IF;
    RAISE EXCEPTION 'market_datasetversion is append-only';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF OLD.manifest ? 'historical_plan_sha256'
       OR NEW.manifest ? 'historical_plan_sha256' THEN
      RAISE EXCEPTION 'historical dataset manifests are immutable';
    END IF;
    RAISE EXCEPTION 'market_datasetversion is append-only';
  END IF;
  IF NOT NEW.manifest ? 'historical_plan_sha256' THEN RETURN NEW; END IF;
  SELECT * INTO STRICT plan FROM market_historicaldatasetplan
    WHERE sha256=NEW.manifest->>'historical_plan_sha256';
  SELECT * INTO STRICT strategy FROM research_strategyversion
    WHERE id=plan.strategy_version_id;
  SELECT jsonb_agg(jsonb_build_object(
           'instrument',instrument.value,
           'granularity',granularity.value,
           'start',plan.ranges->granularity.value->'from',
           'end',plan.ranges->granularity.value->'to')
           ORDER BY instrument.ordinality,granularity.ordinality)
    INTO required_ranges
    FROM jsonb_array_elements_text(plan.instruments)
           WITH ORDINALITY AS instrument(value,ordinality)
    CROSS JOIN jsonb_array_elements_text(plan.granularities)
           WITH ORDINALITY AS granularity(value,ordinality);
  expected_manifest := jsonb_build_object(
    'strategy_manifest_sha256',strategy.content_hash,
    'partition',jsonb_build_object('name','development','start_year',2010,'end_year',2018),
    'required_ranges',required_ranges,
    'historical_plan_sha256',plan.sha256,
    'price_component',plan.price_component,
    'complete_only',plan.complete_only,
    'instruments',plan.instruments,
    'granularities',plan.granularities,
    'alignment',plan.alignment);
  IF NEW.source_id IS DISTINCT FROM plan.source_id
     OR NEW.name IS DISTINCT FROM plan.payload->'dataset'->>'name'
     OR NEW.version IS DISTINCT FROM plan.payload->'dataset'->>'version'
     OR NEW.description IS DISTINCT FROM plan.payload->'dataset'->>'description'
     OR NEW.manifest IS DISTINCT FROM expected_manifest
     OR NEW.manifest_sha256 IS DISTINCT FROM market_sha256(expected_manifest)
  THEN RAISE EXCEPTION 'historical dataset conflicts with portable plan identity'; END IF;
  RETURN NEW;
EXCEPTION WHEN NO_DATA_FOUND THEN
  RAISE EXCEPTION 'historical dataset lacks its canonical plan';
END $$ LANGUAGE plpgsql;
"""

HISTORICAL_DATASET_FUNCTION_0011 = """
CREATE OR REPLACE FUNCTION market_validate_historical_dataset() RETURNS trigger AS $$
DECLARE plan record; strategy record; expected_manifest jsonb; required_ranges jsonb;
BEGIN
  IF NOT NEW.manifest ? 'historical_plan_sha256' THEN RETURN NEW; END IF;
  SELECT * INTO STRICT plan FROM market_historicaldatasetplan
    WHERE sha256=NEW.manifest->>'historical_plan_sha256';
  SELECT * INTO STRICT strategy FROM research_strategyversion
    WHERE id=plan.strategy_version_id;
  SELECT jsonb_agg(jsonb_build_object(
           'instrument',instrument.value,
           'granularity',granularity.value,
           'start',plan.ranges->granularity.value->'from',
           'end',plan.ranges->granularity.value->'to')
           ORDER BY instrument.ordinality,granularity.ordinality)
    INTO required_ranges
    FROM jsonb_array_elements_text(plan.instruments)
           WITH ORDINALITY AS instrument(value,ordinality)
    CROSS JOIN jsonb_array_elements_text(plan.granularities)
           WITH ORDINALITY AS granularity(value,ordinality);
  expected_manifest := jsonb_build_object(
    'strategy_manifest_sha256',strategy.content_hash,
    'partition',jsonb_build_object('name','development','start_year',2010,'end_year',2018),
    'required_ranges',required_ranges,
    'historical_plan_sha256',plan.sha256,
    'price_component',plan.price_component,
    'complete_only',plan.complete_only,
    'instruments',plan.instruments,
    'granularities',plan.granularities,
    'alignment',plan.alignment);
  IF NEW.source_id<>plan.source_id OR NEW.name<>plan.payload->'dataset'->>'name'
     OR NEW.version<>plan.payload->'dataset'->>'version'
     OR NEW.description<>plan.payload->'dataset'->>'description'
     OR NEW.manifest<>expected_manifest
     OR NEW.manifest_sha256<>market_sha256(expected_manifest)
  THEN RAISE EXCEPTION 'historical dataset conflicts with portable plan identity'; END IF;
  RETURN NEW;
EXCEPTION WHEN NO_DATA_FOUND THEN
  RAISE EXCEPTION 'historical dataset lacks its canonical plan';
END $$ LANGUAGE plpgsql;
"""


def install_operation_aware_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP TRIGGER market_historical_dataset_validate ON market_datasetversion;"
        "DROP TRIGGER market_datasetversion_append_only ON market_datasetversion;"
        + HISTORICAL_DATASET_FUNCTION
        + "DROP FUNCTION market_datasetversion_reject_mutation();"
        "CREATE TRIGGER market_historical_dataset_validate BEFORE INSERT OR UPDATE OR DELETE "
        "ON market_datasetversion FOR EACH ROW "
        "EXECUTE FUNCTION market_validate_historical_dataset();"
    )


def restore_0011_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    migration_0011 = import_module("market.migrations.0011_portable_acquisition_identities")
    migration_0011.require_empty_phase2b(apps, schema_editor)
    schema_editor.execute(
        "DROP TRIGGER market_historical_dataset_validate ON market_datasetversion;"
        + HISTORICAL_DATASET_FUNCTION_0011
        + "CREATE TRIGGER market_historical_dataset_validate BEFORE INSERT "
        "ON market_datasetversion FOR EACH ROW "
        "EXECUTE FUNCTION market_validate_historical_dataset();"
        "CREATE FUNCTION market_datasetversion_reject_mutation() RETURNS trigger AS $$"
        "BEGIN RAISE EXCEPTION 'market_datasetversion is append-only'; END;"
        "$$ LANGUAGE plpgsql;"
        "CREATE TRIGGER market_datasetversion_append_only BEFORE UPDATE OR DELETE "
        "ON market_datasetversion FOR EACH ROW "
        "EXECUTE FUNCTION market_datasetversion_reject_mutation();"
    )


class Migration(migrations.Migration):
    dependencies = [("market", "0011_portable_acquisition_identities")]
    operations = [migrations.RunPython(install_operation_aware_trigger, restore_0011_triggers)]
