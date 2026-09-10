"""Phase 4 prerequisite — add M15 to the live candle/observation contract.

This migration makes ``M15`` a supported live granularity for the candle
observation ledger, in lockstep with ``market.quality``:

* the four ``granularity`` fields gain the ``M15`` choice (a validation-only
  change; PostgreSQL stores no CHECK for Django choices, so this is a DB no-op);
* the two PL/pgSQL mirrors installed by migration 0029 —
  ``market_candleobservation_live_interval_is_aligned`` and
  ``market_candleobservation_live_completion`` — are replaced to add the M15
  arm so that raw-SQL observation inserts for M15 candles are accepted with the
  same alignment/completion rule the Python code enforces.
  ``market.tests.test_observation_lineage`` pins the two mirrors against the
  Python definitions across a multi-year DST matrix, including M15.

The migration adds no schedule and no data. ``M15`` is deliberately excluded
from ``SCHEDULED_LIVE_GRANULARITIES`` so the Phase 2 canonical job inventory is
unchanged (see docs/phase4/design.md §3). It is fully reversible: the reverse
restores the exact pre-M15 (H1/H4/D/W-only) function bodies from migration 0029.
No M1 support is added.
"""

from django.db import migrations, models

# Forward: alignment mirror with the M15 arm added before the on-the-hour gate.
ALIGNMENT_WITH_M15 = r"""
CREATE OR REPLACE FUNCTION market_candleobservation_live_interval_is_aligned(
    ts timestamptz,
    granularity text
) RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE
    WHEN granularity NOT IN ('M15', 'H1', 'H4', 'D', 'W') THEN false
    WHEN granularity = 'M15' THEN
      date_trunc('minute', ts AT TIME ZONE 'America/New_York')
        IS NOT DISTINCT FROM (ts AT TIME ZONE 'America/New_York')
      AND date_part('minute', ts AT TIME ZONE 'America/New_York')::int % 15 = 0
    WHEN date_trunc('hour', ts AT TIME ZONE 'America/New_York')
         IS DISTINCT FROM (ts AT TIME ZONE 'America/New_York') THEN false
    WHEN granularity = 'H1' THEN true
    WHEN granularity = 'H4' THEN
      date_part('hour', ts AT TIME ZONE 'America/New_York')::int
        IN (1, 5, 9, 13, 17, 21)
    WHEN date_part('hour', ts AT TIME ZONE 'America/New_York')::int <> 17 THEN false
    WHEN granularity = 'D' THEN
      date_part('dow', ts AT TIME ZONE 'America/New_York')::int IN (0, 1, 2, 3, 4)
    ELSE date_part('dow', ts AT TIME ZONE 'America/New_York')::int = 5
  END
$$;
"""

# Reverse: the exact pre-M15 alignment mirror from migration 0029.
ALIGNMENT_WITHOUT_M15 = r"""
CREATE OR REPLACE FUNCTION market_candleobservation_live_interval_is_aligned(
    ts timestamptz,
    granularity text
) RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE
    WHEN granularity NOT IN ('H1', 'H4', 'D', 'W') THEN false
    WHEN date_trunc('hour', ts AT TIME ZONE 'America/New_York')
         IS DISTINCT FROM (ts AT TIME ZONE 'America/New_York') THEN false
    WHEN granularity = 'H1' THEN true
    WHEN granularity = 'H4' THEN
      date_part('hour', ts AT TIME ZONE 'America/New_York')::int
        IN (1, 5, 9, 13, 17, 21)
    WHEN date_part('hour', ts AT TIME ZONE 'America/New_York')::int <> 17 THEN false
    WHEN granularity = 'D' THEN
      date_part('dow', ts AT TIME ZONE 'America/New_York')::int IN (0, 1, 2, 3, 4)
    ELSE date_part('dow', ts AT TIME ZONE 'America/New_York')::int = 5
  END
$$;
"""

# Forward: completion mirror with the M15 arm (an absolute 15-minute step).
COMPLETION_WITH_M15 = r"""
CREATE OR REPLACE FUNCTION market_candleobservation_live_completion(
    ts timestamptz,
    granularity text
) RETURNS timestamptz
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE granularity
    WHEN 'M15' THEN ts + interval '15 minutes'
    WHEN 'H1' THEN ts + interval '1 hour'
    WHEN 'H4' THEN ts + interval '4 hours'
    WHEN 'D' THEN
      ((ts AT TIME ZONE 'America/New_York')::timestamp + interval '1 day')
        AT TIME ZONE 'America/New_York'
    WHEN 'W' THEN
      ((ts AT TIME ZONE 'America/New_York')::timestamp + interval '7 days')
        AT TIME ZONE 'America/New_York'
    ELSE NULL
  END
$$;
"""

# Reverse: the exact pre-M15 completion mirror from migration 0029.
COMPLETION_WITHOUT_M15 = r"""
CREATE OR REPLACE FUNCTION market_candleobservation_live_completion(
    ts timestamptz,
    granularity text
) RETURNS timestamptz
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE granularity
    WHEN 'H1' THEN ts + interval '1 hour'
    WHEN 'H4' THEN ts + interval '4 hours'
    WHEN 'D' THEN
      ((ts AT TIME ZONE 'America/New_York')::timestamp + interval '1 day')
        AT TIME ZONE 'America/New_York'
    WHEN 'W' THEN
      ((ts AT TIME ZONE 'America/New_York')::timestamp + interval '7 days')
        AT TIME ZONE 'America/New_York'
    ELSE NULL
  END
$$;
"""

GRANULARITIES = (
    ("W", "Weekly"),
    ("D", "Daily"),
    ("H4", "Four-hour"),
    ("H1", "Hourly"),
    ("M15", "Fifteen-minute"),
)


def install_m15_mirrors(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(ALIGNMENT_WITH_M15)
        cursor.execute(COMPLETION_WITH_M15)


def restore_pre_m15_mirrors(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(ALIGNMENT_WITHOUT_M15)
        cursor.execute(COMPLETION_WITHOUT_M15)


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0030_ingestion_eligibility"),
    ]

    operations = [
        migrations.AlterField(
            model_name="candle",
            name="granularity",
            field=models.CharField(choices=GRANULARITIES, max_length=3),
        ),
        migrations.AlterField(
            model_name="candleobservation",
            name="granularity",
            field=models.CharField(choices=GRANULARITIES, max_length=3),
        ),
        migrations.AlterField(
            model_name="ingestionrun",
            name="granularity",
            field=models.CharField(choices=GRANULARITIES, max_length=3),
        ),
        migrations.AlterField(
            model_name="technicalsnapshot",
            name="granularity",
            field=models.CharField(choices=GRANULARITIES, max_length=3),
        ),
        migrations.RunPython(install_m15_mirrors, restore_pre_m15_mirrors),
    ]
