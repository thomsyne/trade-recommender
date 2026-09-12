"""Prospective F3 method/grammar pin only. No row/schema rewrite or activation."""

from importlib import import_module

from django.db import migrations

PRIOR = import_module("research.migrations.0022_phase7_provenance_corrections")
PREDECESSOR_SHA256 = PRIOR.METHOD_SHA256
METHOD_SHA256 = "8200e7f3bc2158c440d6ee8173789c2fc305faeb45ba5ead95f710e22bf759bd"
SOURCE_GRAMMAR = (
    r"(?:(?:USD|CAD|EUR|GBP|Canada|Canadian|United States|European|Europe|UK|British|"
    r"Bank of Canada|Federal Reserve|European Central Bank|Bank of England|ECB|BoC|BoE|Fed)"
    r":? (?:market|inflation|monetary policy|employment|unemployment|economic growth|"
    r"liquidity|financial stress|manufacturing|consumer demand)"
    r"(?: (?:overview|report|statement|outlook|release))?"
    r"|Official (?:overview|report|statement|outlook|release)(?: supplied)?"
    r"|(?:Synthetic|Official) source"
    r"|Bank of Canada|Federal Reserve|European Central Bank|Bank of England)\.?"
)
OLD = PRIOR.OLD_CONTEXT.replace(PRIOR.PRIOR_CONTEXT.METHOD_SHA256, PREDECESSOR_SHA256)
NEW = OLD.replace(PREDECESSOR_SHA256, METHOD_SHA256).replace(
    "section jsonb; claim jsonb;", "section jsonb; claim jsonb; item jsonb; source_value text;"
)
NEW = NEW.replace(
    " FOR section IN SELECT value FROM jsonb_each(result->'output') LOOP",
    """
 FOR item IN SELECT value FROM jsonb_array_elements(req->'input'->'evidence') LOOP
  FOR source_value IN SELECT value FROM jsonb_each_text(item->'fields')
   UNION ALL SELECT item->>'attribution' LOOP
   PERFORM phase7_assert(phase7_source_phrase(source_value));
  END LOOP;
 END LOOP;
 FOR section IN SELECT value FROM jsonb_each(result->'output') LOOP""",
)
NEW = NEW.replace(
    "  END LOOP;\n END LOOP;\n NEW.recorded_at",
    """
   FOR item IN SELECT value FROM jsonb_array_elements(claim->'citations') LOOP
    PERFORM phase7_assert(phase7_source_phrase(item->>'quote'));
   END LOOP;
   IF claim->>'kind'='fact' THEN
    PERFORM phase7_assert(phase7_source_phrase(claim->>'statement'));
   ELSE
    PERFORM phase7_assert(claim->>'statement'=CASE claim->>'relationship'
     WHEN 'uncertain' THEN 'The supplied context does not resolve the uncertainty.'
     WHEN 'conflict' THEN 'The supplied representations require conflict qualification.'
     WHEN 'research' THEN 'Would independent evidence resolve this uncertainty?' END);
   END IF;
  END LOOP;
 END LOOP;
 NEW.recorded_at""",
)
SQL = (
    r"""
CREATE FUNCTION phase7_source_phrase(value text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $function$
 SELECT coalesce(length(value) BETWEEN 1 AND 600
  AND octet_length(value)=char_length(value) AND value !~ '[[:cntrl:]]'
  AND value ~* $grammar$^__GRAMMAR__$grammar$,false)
$function$;
""".replace("__GRAMMAR__", SOURCE_GRAMMAR + "$")
    + NEW
)


class Migration(migrations.Migration):
    dependencies = [("research", "0022_phase7_provenance_corrections")]
    operations = [
        migrations.RunSQL(SQL, OLD + "DROP FUNCTION phase7_source_phrase(text);"),
        migrations.RunPython(migrations.RunPython.noop, PRIOR.refuse_populated_reverse),
    ]
