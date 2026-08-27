from django.db import migrations

TABLES = (
    "research_strategydefinition",
    "research_strategyversion",
    "research_strategyparametermanifest",
    "research_level",
    "research_levellifecycleevent",
    "research_levelproximityevent",
    "research_analysisrun",
    "research_setupevent",
    "research_setuplevelattribution",
    "research_setuptransition",
    "research_entryeligibilityevaluation",
    "research_jobrun",
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


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {table}_reject_mutation();")


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0007_phase_2a_append_only_triggers"),
        ("research", "0009_phase_2a_foundation"),
    ]
    operations = [migrations.RunPython(create_triggers, drop_triggers)]
