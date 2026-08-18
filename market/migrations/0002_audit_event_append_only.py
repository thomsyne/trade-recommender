from django.db import migrations

CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION market_reject_audit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'market_auditevent is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER market_auditevent_append_only
BEFORE UPDATE OR DELETE ON market_auditevent
FOR EACH ROW EXECUTE FUNCTION market_reject_audit_mutation();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS market_auditevent_append_only ON market_auditevent;
DROP FUNCTION IF EXISTS market_reject_audit_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("market", "0001_initial")]
    operations = [migrations.RunSQL(CREATE_TRIGGER, DROP_TRIGGER)]
