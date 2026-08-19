from django.db import migrations

TABLES = (
    "forecasts_targetcontract",
    "forecasts_evidencesnapshot",
    "forecasts_forecast",
    "forecasts_forecastresolution",
)

CREATE_TRIGGERS = "\n".join(
    f"""
CREATE OR REPLACE FUNCTION reject_mutation_{table}()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '{table} is immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER {table}_immutable
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION reject_mutation_{table}();
"""
    for table in TABLES
)

DROP_TRIGGERS = "\n".join(
    f"""
DROP TRIGGER IF EXISTS {table}_immutable ON {table};
DROP FUNCTION IF EXISTS reject_mutation_{table}();
"""
    for table in TABLES
)


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0001_initial")]
    operations = [migrations.RunSQL(CREATE_TRIGGERS, DROP_TRIGGERS)]
