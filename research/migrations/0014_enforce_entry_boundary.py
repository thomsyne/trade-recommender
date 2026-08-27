from datetime import time, timedelta
from importlib import import_module
from zoneinfo import ZoneInfo

from django.db import migrations

_lineage = import_module("research.migrations.0013_finalize_phase_2a_lineage")


def _expected_entry(confirmation):
    local = confirmation.astimezone(ZoneInfo("America/New_York"))
    if local.weekday() == 4 and local.time().replace(tzinfo=None) == time(17):
        return (local + timedelta(days=2)).replace(hour=17).astimezone(confirmation.tzinfo)
    return confirmation


def assert_existing_entry_boundaries(apps, schema_editor):
    Transition = apps.get_model("research", "SetupTransition")
    Evaluation = apps.get_model("research", "EntryEligibilityEvaluation")
    confirmations = {
        setup_id: effective_at
        for setup_id, effective_at in Transition.objects.filter(
            from_state="TRIGGER_PENDING", to_state="CONFIRMED", book_identity=""
        ).values_list("setup_id", "effective_at")
    }
    for transition in Transition.objects.filter(from_state="CONFIRMED"):
        confirmation = confirmations.get(transition.setup_id)
        if confirmation is None or transition.effective_at != _expected_entry(confirmation):
            raise RuntimeError("existing book transition is not at the confirmation-derived entry")
    for evaluation in Evaluation.objects.filter(decision="ENTRY_PENDING"):
        confirmation = confirmations.get(evaluation.setup_id)
        if confirmation is None or evaluation.entry_timestamp != _expected_entry(confirmation):
            raise RuntimeError("existing entry evaluation is not at the confirmation-derived entry")


def create_entry_boundary_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _lineage.drop_lineage_triggers(apps, schema_editor)
    schema_editor.execute(
        """
        CREATE FUNCTION research_confirmation_entry_boundary(setup_key bigint)
        RETURNS timestamptz AS $$
        DECLARE
            confirmation_at timestamptz;
            confirmation_local timestamp;
        BEGIN
            SELECT effective_at INTO STRICT confirmation_at
              FROM research_setuptransition
             WHERE setup_id = setup_key
               AND from_state = 'TRIGGER_PENDING'
               AND to_state = 'CONFIRMED'
               AND book_identity = '';
            confirmation_local := confirmation_at AT TIME ZONE 'America/New_York';
            IF extract(isodow FROM confirmation_local) = 5
               AND confirmation_local::time = time '17:00:00' THEN
                RETURN (confirmation_local + interval '2 days')
                       AT TIME ZONE 'America/New_York';
            END IF;
            RETURN confirmation_at;
        EXCEPTION WHEN NO_DATA_FOUND THEN
            RAISE EXCEPTION 'entry record requires one global confirmed transition';
        END;
        $$ LANGUAGE plpgsql STABLE;

        CREATE FUNCTION research_validate_setup_transition() RETURNS trigger AS $$
        DECLARE
            setup_strategy bigint;
            setup_dataset bigint;
            setup_execution text;
            job_strategy bigint;
            job_dataset bigint;
            expected_entry timestamptz;
        BEGIN
            SELECT setup.strategy_version_id, setup.dataset_version_id,
                   strategy.execution_identity
              INTO setup_strategy, setup_dataset, setup_execution
              FROM research_setupevent setup
              JOIN research_strategyversion strategy
                ON strategy.id = setup.strategy_version_id
             WHERE setup.id = NEW.setup_id;
            IF NEW.strategy_version_id <> setup_strategy
               OR NEW.dataset_version_id <> setup_dataset
               OR NEW.execution_identity <> setup_execution THEN
                RAISE EXCEPTION 'setup transition lineage conflicts with setup';
            END IF;
            IF NEW.job_run_id IS NOT NULL THEN
                SELECT strategy_version_id, dataset_version_id
                  INTO job_strategy, job_dataset
                  FROM research_jobrun WHERE id = NEW.job_run_id;
                IF job_strategy <> setup_strategy OR job_dataset <> setup_dataset THEN
                    RAISE EXCEPTION 'setup transition job lineage conflicts with setup';
                END IF;
            END IF;
            IF NEW.from_state = 'CONFIRMED' THEN
                expected_entry := research_confirmation_entry_boundary(NEW.setup_id);
                IF NEW.effective_at IS DISTINCT FROM expected_entry THEN
                    RAISE EXCEPTION 'book transition is not at the confirmation-derived entry';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_setup_transition_validate
        BEFORE INSERT ON research_setuptransition
        FOR EACH ROW EXECUTE FUNCTION research_validate_setup_transition();

        CREATE FUNCTION research_validate_entry_target() RETURNS trigger AS $$
        DECLARE
            level_key text;
            level_lower numeric;
            level_upper numeric;
            level_instrument bigint;
            level_strategy bigint;
            level_dataset bigint;
            level_role text;
            setup_direction text;
            setup_instrument bigint;
            setup_strategy bigint;
            setup_dataset bigint;
            expected_entry timestamptz;
        BEGIN
            IF NEW.decision = 'ENTRY_PENDING' THEN
                expected_entry := research_confirmation_entry_boundary(NEW.setup_id);
                IF NEW.entry_timestamp IS DISTINCT FROM expected_entry THEN
                    RAISE EXCEPTION 'entry evaluation is not at the confirmation-derived entry';
                END IF;
                SELECT stable_key, zone_lower, zone_upper, instrument_id,
                       strategy_version_id, dataset_version_id, role
                  INTO level_key, level_lower, level_upper, level_instrument,
                       level_strategy, level_dataset, level_role
                  FROM research_level WHERE id = NEW.target_level_id;
                SELECT direction, instrument_id, strategy_version_id, dataset_version_id
                  INTO setup_direction, setup_instrument, setup_strategy, setup_dataset
                  FROM research_setupevent WHERE id = NEW.setup_id;
                IF NEW.target_stable_key <> level_key
                   OR level_instrument <> setup_instrument
                   OR level_strategy <> setup_strategy
                   OR level_dataset <> setup_dataset
                   OR (setup_direction = 'long' AND level_role <> 'resistance')
                   OR (setup_direction = 'short' AND level_role <> 'support')
                   OR (setup_direction = 'long' AND NEW.target_price <> level_lower)
                   OR (setup_direction = 'short' AND NEW.target_price <> level_upper) THEN
                    RAISE EXCEPTION 'entry target conflicts with frozen level boundary or lineage';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_entry_target_validate
        BEFORE INSERT ON research_entryeligibilityevaluation
        FOR EACH ROW EXECUTE FUNCTION research_validate_entry_target();
        """
    )


def restore_lineage_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _lineage.drop_lineage_triggers(apps, schema_editor)
    schema_editor.execute("DROP FUNCTION IF EXISTS research_confirmation_entry_boundary(bigint);")
    _lineage.create_lineage_triggers(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("research", "0013_finalize_phase_2a_lineage")]

    operations = [
        migrations.RunPython(
            code=assert_existing_entry_boundaries,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            code=create_entry_boundary_triggers,
            reverse_code=restore_lineage_triggers,
        ),
    ]
