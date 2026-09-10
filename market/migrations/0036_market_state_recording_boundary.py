"""Database first-known time, serialized evidence and retrospective snapshots.

NULL means the recording time of pre-migration evidence is unknown. No source
timestamp or historical row is backfilled. New evidence always receives a DB
timestamp after acquiring the same series lock used by snapshot validation.
"""

from importlib import import_module

from django.db import migrations, models

previous = import_module("market.migrations.0035_market_state_evidence_guards")
NEW_FUNCTIONS = previous.NEW_FUNCTIONS.replace("0.10.0", "0.11.0").replace(
    previous.DESCRIPTOR_0100_SHA256,
    "e701738372efd48e8a0bacf22e6c2956c4af624b0ad794c8289c812d8e5e1cbc",
)
OLD_EVIDENCE = previous.SQL[
    previous.SQL.index("CREATE FUNCTION market_state_evidence_insert_v2()") : previous.SQL.index(
        "CREATE TRIGGER market_state_z_evidence"
    )
].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")
OLD_RESEARCH = previous.SQL[
    previous.SQL.index(
        "CREATE FUNCTION market_research_semantics_immutable_v1()"
    ) : previous.SQL.index("CREATE TRIGGER market_research_policy_semantics")
].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


def availability(sql):
    return sql.replace(
        "c.observed_at<=NEW.information_cutoff",
        "c.observed_at<=NEW.information_cutoff "
        "AND (c.recorded_at IS NULL OR c.recorded_at<=NEW.information_cutoff)",
    )


SQL = r"""
CREATE FUNCTION market_state_lock_series(instrument bigint, granularities text[])
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE g text;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'market_state_requires_read_committed' USING ERRCODE='23514';
  END IF;
  FOR g IN SELECT DISTINCT unnest(granularities) ORDER BY 1 LOOP
    PERFORM pg_advisory_xact_lock(hashtextextended('live-candles:' || instrument || ':' || g, 0));
  END LOOP;
END;
$$;

CREATE FUNCTION market_observation_recording_boundary() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM market_state_lock_series(NEW.instrument_id, ARRAY[NEW.granularity::text]);
  -- Strictly after an existing cutoff even at clock-resolution equality or
  -- after a wall-clock correction. A caller-supplied timestamp is ignored.
  SELECT greatest(clock_timestamp(), max(information_cutoff) + interval '1 microsecond')
    INTO NEW.recorded_at FROM market_marketstatesnapshot WHERE instrument_id=NEW.instrument_id;
  RETURN NEW;
END;
$$;
CREATE TRIGGER market_candleobservation_a_recording BEFORE INSERT ON market_candleobservation
FOR EACH ROW EXECUTE FUNCTION market_observation_recording_boundary();

CREATE FUNCTION market_state_synchronize() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  PERFORM market_state_lock_series(NEW.instrument_id,
    ARRAY(SELECT jsonb_array_elements_text(NEW.output_payload->'requested_granularities'))
      || ARRAY['M15','D','W']);
  IF NEW.information_cutoff > clock_timestamp() THEN
    RAISE EXCEPTION 'future_market_state_cutoff' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER market_state_a_synchronize BEFORE INSERT ON market_marketstatesnapshot
FOR EACH ROW EXECUTE FUNCTION market_state_synchronize();
"""

# Semantic identity is fixed at registration, not at a racy first reference.
# Editorial and acquisition settings remain editable. No rows are rewritten.
NEW_RESEARCH = OLD_RESEARCH.replace(
    "\n      AND (EXISTS(SELECT 1 FROM research_rawretrieval WHERE source_policy_id=OLD.id)"
    "\n        OR EXISTS(SELECT 1 FROM research_macroseries WHERE source_policy_id=OLD.id))",
    "",
).replace(
    "\n      AND (EXISTS(SELECT 1 FROM research_macroobservation WHERE series_id=OLD.id)"
    "\n        OR EXISTS(SELECT 1 FROM research_economicevent WHERE series_id=OLD.id))",
    "",
)

REVERSE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM market_candleobservation WHERE recorded_at IS NOT NULL) THEN
    RAISE EXCEPTION '0036 cannot discard recorded evidence availability';
  END IF;
END $$;
DROP TRIGGER market_state_a_synchronize ON market_marketstatesnapshot;
DROP FUNCTION market_state_synchronize();
DROP TRIGGER market_candleobservation_a_recording ON market_candleobservation;
DROP FUNCTION market_observation_recording_boundary();
DROP FUNCTION market_state_lock_series(bigint,text[]);
"""


class Migration(migrations.Migration):
    dependencies = [("market", "0035_market_state_evidence_guards")]
    operations = [
        migrations.AddField(
            model_name="candleobservation",
            name="recorded_at",
            field=models.DateTimeField(null=True, editable=False),
        ),
        migrations.RunSQL(
            SQL + availability(NEW_FUNCTIONS) + availability(OLD_EVIDENCE) + NEW_RESEARCH,
            REVERSE + previous.NEW_FUNCTIONS + OLD_EVIDENCE + OLD_RESEARCH,
        ),
    ]
