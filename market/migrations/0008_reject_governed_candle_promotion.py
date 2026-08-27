from django.db import migrations

FORWARD_SQL = """
DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;
DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();
CREATE FUNCTION market_governed_candle_reject_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.dataset_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'governed dataset candles are append-only';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.dataset_version_id IS NOT NULL OR NEW.dataset_version_id IS NOT NULL THEN
        RAISE EXCEPTION 'governed dataset candles must be inserted and are append-only';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER market_governed_candle_append_only
BEFORE UPDATE OR DELETE ON market_candle
FOR EACH ROW EXECUTE FUNCTION market_governed_candle_reject_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS market_governed_candle_append_only ON market_candle;
DROP FUNCTION IF EXISTS market_governed_candle_reject_mutation();
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


def apply_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD_SQL)


def reverse_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE_SQL)


class Migration(migrations.Migration):
    dependencies = [("market", "0007_phase_2a_append_only_triggers")]
    operations = [migrations.RunPython(apply_trigger, reverse_trigger)]
