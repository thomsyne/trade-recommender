from django.db import migrations

TABLES = (
    "market_datasetversion",
    "market_ingestionmanifest",
    "market_candleconflict",
    "market_dataqualityincident",
)


def create_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        function = f"{table}_reject_mutation"
        trigger = f"{table}_append_only"
        schema_editor.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{table} is append-only';
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}();
            """
        )
    schema_editor.execute(
        """
        CREATE FUNCTION market_governed_candle_reject_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.dataset_version_id IS NOT NULL THEN
                RAISE EXCEPTION 'governed dataset candles are append-only';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER market_governed_candle_append_only
        BEFORE UPDATE OR DELETE ON market_candle
        FOR EACH ROW EXECUTE FUNCTION market_governed_candle_reject_mutation();
        """
    )


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {table}_reject_mutation();")
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();")


class Migration(migrations.Migration):
    dependencies = [("market", "0006_phase_2a_foundation")]
    operations = [migrations.RunPython(create_triggers, drop_triggers)]
