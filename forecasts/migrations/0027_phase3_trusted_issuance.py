from django.db import migrations, models

SQL = r"""
CREATE FUNCTION phase3_trusted_issuance() RETURNS trigger AS $$
BEGIN
 NEW.recorded_at:=clock_timestamp();
 IF NEW.contract_version<>4 AND EXISTS(
  SELECT 1 FROM forecasts_experimentera e JOIN forecasts_forecastmethodidentity m ON m.id=e.method_id
  WHERE m.contract_version=4 AND (e.starts_at<=NEW.recorded_at OR e.starts_at<=NEW.generated_at)
 ) THEN RAISE EXCEPTION 'prospective_contract_downgrade'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER phase3_00_trusted_issuance BEFORE INSERT ON forecasts_recommendation FOR EACH ROW EXECUTE FUNCTION phase3_trusted_issuance();
"""


class Migration(migrations.Migration):
    dependencies = [("forecasts", "0026_phase3_price_and_availability")]
    operations = [
        migrations.AddField(
            model_name="recommendation",
            name="recorded_at",
            field=models.DateTimeField(null=True, blank=True, editable=False),
        ),
        migrations.RunSQL(SQL),
    ]
