from django.db import migrations

CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION reject_mutation_research_economicevent()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'research_economicevent is immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_economicevent_immutable
BEFORE UPDATE OR DELETE ON research_economicevent
FOR EACH ROW EXECUTE FUNCTION reject_mutation_research_economicevent();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS research_economicevent_immutable ON research_economicevent;
DROP FUNCTION IF EXISTS reject_mutation_research_economicevent();
"""


class Migration(migrations.Migration):
    dependencies = [("research", "0004_macroobservation_provider_status_and_more")]
    operations = [migrations.RunSQL(CREATE_TRIGGER, DROP_TRIGGER)]
