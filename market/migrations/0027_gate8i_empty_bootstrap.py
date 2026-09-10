"""Install prospective Gate 8I authority without asserting acquisition evidence.

Only a completely empty application database has an additional installation
path. Populated histories still execute the published acceptance operation.
"""

from importlib import import_module

from django.db import migrations

original = import_module("market.migrations.0027_gate8i_final_dataset_acceptance")

# Django creates these bookkeeping rows independently of application evidence.
FRAMEWORK_TABLES = {"django_migrations", "django_content_type", "auth_permission"}


def forward(apps, schema_editor):
    connection = schema_editor.connection
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND c.relkind IN ('r','p','f','m') "
            "ORDER BY c.relname"
        )
        tables = {row[0] for row in cursor.fetchall()} - FRAMEWORK_TABLES
        expected = {
            model._meta.db_table
            for model in apps.get_app_config("market").get_models()
            if model._meta.managed
        }
        if not expected.issubset(tables):
            raise RuntimeError("Gate 8I bootstrap requires every historical market table")
        # Hold the entire inspected domain stable until the atomic migration
        # commits. Include unknown tables rather than assuming they are harmless.
        cursor.execute(
            "LOCK TABLE "
            + ", ".join(quote(table) for table in sorted(tables))
            + " IN ACCESS EXCLUSIVE MODE"
        )
        populated = False
        for table in sorted(tables):
            cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {quote(table)})")
            populated |= cursor.fetchone()[0]
        if populated:
            original.forward(apps, schema_editor)
            return

        before = original._require_0026_catalog(cursor)
        original.gate8g._install(
            cursor,
            "market_validate_replacement_registration(reg market_datasetregistration)",
            "void",
            original.GATE8I_REGISTRATION_PROSRC,
        )
        after = original.gate8g._catalog(cursor)
        if original._without_registration_validator(
            after
        ) != original._without_registration_validator(before):
            raise RuntimeError("Gate 8I bootstrap altered an unrelated governance object")
        if (
            original.gate8g._installed_body(cursor, "market_validate_replacement_registration")
            != original.GATE8I_REGISTRATION_PROSRC
        ):
            raise RuntimeError("Gate 8I bootstrap did not install the exact registration validator")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("market", "0026_gate8g_successor_acquisition_activation")]
    replaces = [("market", "0027_gate8i_final_dataset_acceptance")]
    operations = [migrations.RunPython(forward, original.reverse)]
