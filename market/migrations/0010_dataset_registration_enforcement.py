import django.db.models.deletion
from django.db import migrations, models


def preflight(apps, schema_editor):
    IngestionRun = apps.get_model("market", "IngestionRun")
    invalid = IngestionRun.objects.exclude(
        status__in=("running", "succeeded", "failed", "quarantined")
    ).exists()
    if invalid:
        raise RuntimeError("ingestion run has an unsupported status")


def create_governance_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE FUNCTION market_phase2b_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '%% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER market_historical_plan_immutable
        BEFORE UPDATE OR DELETE ON market_historicaldatasetplan
        FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();
        CREATE TRIGGER market_historical_chunk_immutable
        BEFORE UPDATE OR DELETE ON market_historicalingestionchunk
        FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();
        CREATE TRIGGER market_historical_attempt_immutable
        BEFORE UPDATE OR DELETE ON market_historicalingestionattempt
        FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();
        CREATE TRIGGER market_dataset_registration_immutable
        BEFORE UPDATE OR DELETE ON market_datasetregistration
        FOR EACH ROW EXECUTE FUNCTION market_phase2b_immutable();

        CREATE FUNCTION market_validate_historical_chunk() RETURNS trigger AS $$
        DECLARE
            plan_hash text;
            plan_price text;
            dataset_plan_hash text;
        BEGIN
            SELECT sha256, price_component INTO plan_hash, plan_price
              FROM market_historicaldatasetplan WHERE id = NEW.plan_id;
            SELECT manifest->>'historical_plan_sha256' INTO dataset_plan_hash
              FROM market_datasetversion WHERE id = NEW.dataset_version_id;
            IF dataset_plan_hash IS DISTINCT FROM plan_hash
               OR plan_price <> 'COMBINED_BID_ASK'
               OR NEW.canonical_request->>'price' <> 'BA'
               OR NEW.canonical_request->>'price_component' <> 'COMBINED_BID_ASK'
               OR NEW.canonical_request->>'complete_only' <> 'true'
               OR NEW.requested_to >= timestamptz '2019-01-01 05:00:00+00' THEN
                RAISE EXCEPTION 'historical chunk conflicts with its frozen plan or boundary';
            END IF;
            IF EXISTS (
                SELECT 1 FROM market_datasetregistration
                 WHERE dataset_version_id = NEW.dataset_version_id
            ) THEN
                RAISE EXCEPTION 'registered historical dataset is sealed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_historical_chunk_validate
        BEFORE INSERT ON market_historicalingestionchunk
        FOR EACH ROW EXECUTE FUNCTION market_validate_historical_chunk();

        CREATE FUNCTION market_validate_historical_attempt() RETURNS trigger AS $$
        DECLARE
            chunk_row market_historicalingestionchunk%%ROWTYPE;
            run_row market_ingestionrun%%ROWTYPE;
            plan_source bigint;
        BEGIN
            SELECT * INTO STRICT chunk_row FROM market_historicalingestionchunk
             WHERE id = NEW.chunk_id;
            SELECT * INTO STRICT run_row FROM market_ingestionrun
             WHERE id = NEW.ingestion_run_id;
            SELECT source_id INTO STRICT plan_source FROM market_historicaldatasetplan
             WHERE id = chunk_row.plan_id;
            IF run_row.status <> 'running'
               OR run_row.source_id <> plan_source
               OR run_row.dataset_version_id <> chunk_row.dataset_version_id
               OR run_row.instrument_id <> chunk_row.instrument_id
               OR run_row.granularity <> chunk_row.granularity
               OR run_row.requested_from <> chunk_row.requested_from
               OR run_row.requested_to <> chunk_row.requested_to
               OR run_row.parameters IS DISTINCT FROM chunk_row.canonical_request
               OR NEW.idempotency_key <> 'failed-break-ingestion-attempt:'
                    || chunk_row.logical_key || ':' || NEW.attempt_number::text THEN
                RAISE EXCEPTION 'historical attempt run lineage conflicts with logical chunk';
            END IF;
            IF EXISTS (
                SELECT 1 FROM market_datasetregistration
                 WHERE dataset_version_id = chunk_row.dataset_version_id
            ) THEN
                RAISE EXCEPTION 'registered historical dataset is sealed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_historical_attempt_validate
        BEFORE INSERT ON market_historicalingestionattempt
        FOR EACH ROW EXECUTE FUNCTION market_validate_historical_attempt();

        CREATE FUNCTION market_ingestion_run_transition() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'running' OR EXISTS (
                    SELECT 1 FROM market_historicalingestionattempt
                     WHERE ingestion_run_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'ingestion runs with audit lineage cannot be deleted';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status <> 'running'
               OR NEW.status NOT IN ('succeeded', 'failed', 'quarantined')
               OR NEW.finished_at IS NULL
               OR NEW.source_id <> OLD.source_id
               OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id
               OR NEW.instrument_id <> OLD.instrument_id
               OR NEW.granularity <> OLD.granularity
               OR NEW.requested_from <> OLD.requested_from
               OR NEW.requested_to <> OLD.requested_to
               OR NEW.parameters IS DISTINCT FROM OLD.parameters
               OR NEW.request_manifest_hash <> OLD.request_manifest_hash
               OR NEW.started_at <> OLD.started_at THEN
                RAISE EXCEPTION 'ingestion run may transition only once from running to terminal';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_ingestion_run_transition_enforce
        BEFORE UPDATE OR DELETE ON market_ingestionrun
        FOR EACH ROW EXECUTE FUNCTION market_ingestion_run_transition();

        DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;
        DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();
        CREATE FUNCTION market_governed_candle_reject_mutation() RETURNS trigger AS $$
        DECLARE
            chunk_row market_historicalingestionchunk%%ROWTYPE;
            historical_plan text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.dataset_version_id IS NOT NULL THEN
                    RAISE EXCEPTION 'governed dataset candles are append-only';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.dataset_version_id IS NOT NULL OR NEW.dataset_version_id IS NOT NULL THEN
                    RAISE EXCEPTION 'governed dataset candles must be inserted and are append-only';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.dataset_version_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF EXISTS (
                SELECT 1 FROM market_datasetregistration
                 WHERE dataset_version_id = NEW.dataset_version_id
            ) THEN
                RAISE EXCEPTION 'registered historical dataset is sealed';
            END IF;
            SELECT manifest->>'historical_plan_sha256' INTO historical_plan
              FROM market_datasetversion WHERE id = NEW.dataset_version_id;
            IF historical_plan IS NOT NULL THEN
                SELECT chunk.* INTO chunk_row
                  FROM market_historicalingestionattempt attempt
                  JOIN market_historicalingestionchunk chunk ON chunk.id = attempt.chunk_id
                 WHERE attempt.ingestion_run_id = NEW.ingestion_run_id;
                IF chunk_row.id IS NULL
                   OR chunk_row.dataset_version_id <> NEW.dataset_version_id
                   OR chunk_row.instrument_id <> NEW.instrument_id
                   OR chunk_row.granularity <> NEW.granularity
                   OR NEW.timestamp < chunk_row.requested_from
                   OR NEW.timestamp >= chunk_row.requested_to THEN
                    RAISE EXCEPTION 'historical candle conflicts with logical chunk lineage';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_governed_candle_append_only
        BEFORE INSERT OR UPDATE OR DELETE ON market_candle
        FOR EACH ROW EXECUTE FUNCTION market_governed_candle_reject_mutation();

        CREATE FUNCTION market_validate_dataset_registration() RETURNS trigger AS $$
        DECLARE
            plan_hash text;
            dataset_plan_hash text;
        BEGIN
            SELECT sha256 INTO STRICT plan_hash FROM market_historicaldatasetplan
             WHERE id = NEW.plan_id;
            SELECT manifest->>'historical_plan_sha256' INTO STRICT dataset_plan_hash
              FROM market_datasetversion WHERE id = NEW.dataset_version_id;
            IF dataset_plan_hash IS DISTINCT FROM plan_hash THEN
                RAISE EXCEPTION 'dataset registration plan lineage conflicts';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM market_historicalingestionchunk chunk
                 WHERE chunk.plan_id = NEW.plan_id
                   AND chunk.dataset_version_id = NEW.dataset_version_id
            ) OR EXISTS (
                SELECT 1 FROM market_ingestionrun run
                 WHERE run.dataset_version_id = NEW.dataset_version_id
                   AND NOT EXISTS (
                       SELECT 1 FROM market_historicalingestionattempt attempt
                        WHERE attempt.ingestion_run_id = run.id
                   )
            ) OR EXISTS (
                SELECT 1 FROM market_historicalingestionchunk chunk
                 WHERE chunk.plan_id = NEW.plan_id
                   AND chunk.dataset_version_id = NEW.dataset_version_id
                   AND (
                       SELECT count(*) FROM market_historicalingestionattempt attempt
                       JOIN market_ingestionrun run ON run.id = attempt.ingestion_run_id
                       WHERE attempt.chunk_id = chunk.id AND run.status = 'succeeded'
                   ) <> 1
            ) OR EXISTS (
                SELECT 1 FROM market_ingestionrun run
                JOIN market_historicalingestionattempt attempt
                  ON attempt.ingestion_run_id = run.id
                JOIN market_historicalingestionchunk chunk ON chunk.id = attempt.chunk_id
                 WHERE chunk.dataset_version_id = NEW.dataset_version_id
                   AND run.status = 'running'
            ) OR EXISTS (
                SELECT 1 FROM market_candleconflict
                 WHERE dataset_version_id = NEW.dataset_version_id
            ) OR EXISTS (
                SELECT 1 FROM market_dataqualityincident
                 WHERE dataset_version_id = NEW.dataset_version_id
            ) THEN
                RAISE EXCEPTION 'dataset is not eligible for immutable registration';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_dataset_registration_validate
        BEFORE INSERT ON market_datasetregistration
        FOR EACH ROW EXECUTE FUNCTION market_validate_dataset_registration();
        """
    )


def drop_governance_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS market_dataset_registration_validate ON market_datasetregistration;
        DROP FUNCTION IF EXISTS market_validate_dataset_registration();
        DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;
        DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();
        DROP TRIGGER IF EXISTS market_ingestion_run_transition_enforce ON market_ingestionrun;
        DROP FUNCTION IF EXISTS market_ingestion_run_transition();
        DROP TRIGGER IF EXISTS market_historical_attempt_validate ON market_historicalingestionattempt;
        DROP FUNCTION IF EXISTS market_validate_historical_attempt();
        DROP TRIGGER IF EXISTS market_historical_chunk_validate ON market_historicalingestionchunk;
        DROP FUNCTION IF EXISTS market_validate_historical_chunk();
        DROP TRIGGER IF EXISTS market_dataset_registration_immutable ON market_datasetregistration;
        DROP TRIGGER IF EXISTS market_historical_attempt_immutable ON market_historicalingestionattempt;
        DROP TRIGGER IF EXISTS market_historical_chunk_immutable ON market_historicalingestionchunk;
        DROP TRIGGER IF EXISTS market_historical_plan_immutable ON market_historicaldatasetplan;
        DROP FUNCTION IF EXISTS market_phase2b_immutable();
        """
    )
    from importlib import import_module

    prior = import_module("market.migrations.0008_reject_governed_candle_promotion")
    prior.apply_trigger(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("market", "0009_historical_dataset_governance")]

    operations = [
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.CreateModel(
            name="DatasetRegistration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("series_manifest", models.JSONField()),
                ("row_counts", models.JSONField()),
                ("first_last_timestamps", models.JSONField()),
                ("missingness", models.JSONField()),
                ("conflict_count", models.PositiveIntegerField()),
                ("incident_count", models.PositiveIntegerField()),
                ("logical_chunk_set_hash", models.CharField(max_length=64)),
                ("successful_attempt_set_hash", models.CharField(max_length=64)),
                ("ingestion_manifest_set_hash", models.CharField(max_length=64)),
                ("candle_key_hash", models.CharField(max_length=64)),
                ("candle_payload_hash", models.CharField(max_length=64)),
                ("configuration_sha256", models.CharField(max_length=64)),
                ("report_sha256", models.CharField(max_length=64, unique=True)),
                ("registered_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dataset_version",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration",
                        to="market.datasetversion",
                    ),
                ),
                (
                    "plan",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration",
                        to="market.historicaldatasetplan",
                    ),
                ),
            ],
            options={"abstract": False},
        ),
        migrations.RunPython(create_governance_triggers, drop_governance_triggers),
    ]
