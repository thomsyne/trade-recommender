"""Phase 1.4 enforcement — dense per-candle observation lineage.

Migration 0028 created ``market_candleobservation`` with revision chains keyed
per ``(series, source)`` even though the canonical candle identity is
source-independent. That allowed a second source (or a first observation of a
legacy row) to insert ``revision=2`` with no predecessor, and nothing verified
source/run/candle consistency, dense predecessor linkage, or that
``content_sha256`` recomputes from the row's own content.

This migration makes the chain belong to the candle:

* ``revision`` is the row's position in the candle's view history across all
  sources and ``supersedes`` points at revision N-1 of the same candle, so the
  unique key becomes ``(candle, revision)``;
* existing rows are renumbered dense by insertion order (``id``) inside one
  transaction with the append-only trigger suspended; a legacy adoption row
  that was written as revision 2 with no supersedes becomes revision 1, and a
  cross-source row that was written with no predecessor is relinked onto the
  chain head;
* a PostgreSQL BEFORE INSERT trigger rejects rows whose source/run/candle are
  inconsistent, whose chain is not dense, or whose ``content_sha256`` does not
  recompute from the stored content (via ``pgcrypto`` and a SQL mirror of the
  Python canonical hash, ``market_candleobservation_content_sha256``). The SQL
  mirror formats prices through ``market_candleobservation_canonical_price`` so
  sub-unit magnitudes hash identically on both sides. The trigger also refuses
  provenance forgeries that a valid hash alone would bless: an observation
  timestamp outside its run's request window, a run recorded as failed or
  quarantined, an ``interval_end`` that is not the exact completion of its
  interval (H1/H4 pure UTC steps; D/W the 17:00 America/New_York wall-clock
  step, computed by ``market_candleobservation_live_completion``) or that runs
  past the request window, an ``observed_at`` that is not contemporaneous with
  its run, and a ``differing_fields`` claim that does not match the content
  actually superseded (recomputed through
  ``market_candleobservation_differing_fields``). Initial and late-arrival
  observations must open the chain with an empty ``differing_fields``;
* the renumber preflight applies the same provenance checks the trigger
  enforces, and the renumber statement rewrites the self-referential
  ``supersedes`` foreign key, whose deferred check would otherwise leave
  ``pending trigger events`` that block the migration's own ``ALTER TABLE ...
  ADD CONSTRAINT`` on any non-empty ledger; ``SET CONSTRAINTS ALL IMMEDIATE``
  flushes them before the schema statements run;
* all helper functions pin ``search_path`` to ``pg_catalog`` (public tables
  and helpers are schema-qualified) so no search-path hijack can shadow them;
* only chain-metadata columns (``revision``/``supersedes_id``) are ever
  rewritten; evidence content, identity and timestamps are untouched.

Reversal is forward-only once observations exist, following migration 0028:
unapplying would re-permit non-dense chains and could not restore the
per-source numbering without rewriting rows. The reverse preflight refuses
before any object is dropped.
"""

from django.db import migrations, models

CREATE_PGCRYPTO_SQL = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"

# Canonical six-decimal formatting shared with market/services.py's
# ``format(value, '.6f')``: exactly six fraction digits, a leading zero for
# sub-unit magnitudes, and no leading whitespace. PostgreSQL's ``to_char``
# omits the leading zero for ``abs(value) < 1``, which silently diverged the
# SQL hash from the Python hash for ordinary sub-unit prices (e.g. AUD/USD
# around 0.65); every price field must pass through this formatter so both
# sides hash identical JSON.
_CANONICAL_NUMERIC_FORMAT = r"""
CREATE FUNCTION market_candleobservation_canonical_price(value numeric) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE
    WHEN value = 0 THEN '0.000000'
    WHEN abs(value) < 1 THEN
      CASE WHEN value < 0 THEN '-0.' ELSE '0.' END
      || substr(ltrim(to_char(value, '999999999999.999999'), ' '),
                CASE WHEN value < 0 THEN 3 ELSE 2 END)
    ELSE ltrim(to_char(value, '999999999999.999999'), ' ')
  END
$$;
"""

DROP_CANONICAL_NUMERIC_FORMAT_SQL = (
    "DROP FUNCTION IF EXISTS market_candleobservation_canonical_price(numeric);"
)

DROP_CONTENT_HASH_SQL = "DROP FUNCTION IF EXISTS market_candleobservation_content_sha256(text, text, timestamptz, boolean, integer, numeric, numeric, numeric, numeric, numeric, numeric, numeric, numeric);"

CREATE_CONTENT_HASH_SQL = r"""
CREATE FUNCTION market_candleobservation_content_sha256(
    instrument_code text,
    granularity text,
    ts timestamptz,
    complete boolean,
    volume integer,
    bid_open numeric,
    bid_high numeric,
    bid_low numeric,
    bid_close numeric,
    ask_open numeric,
    ask_high numeric,
    ask_low numeric,
    ask_close numeric
) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
  SELECT encode(public.digest(
    '{"ask_close":"' || public.market_candleobservation_canonical_price(ask_close) || '"'
    || ',"ask_high":"' || public.market_candleobservation_canonical_price(ask_high) || '"'
    || ',"ask_low":"' || public.market_candleobservation_canonical_price(ask_low) || '"'
    || ',"ask_open":"' || public.market_candleobservation_canonical_price(ask_open) || '"'
    || ',"bid_close":"' || public.market_candleobservation_canonical_price(bid_close) || '"'
    || ',"bid_high":"' || public.market_candleobservation_canonical_price(bid_high) || '"'
    || ',"bid_low":"' || public.market_candleobservation_canonical_price(bid_low) || '"'
    || ',"bid_open":"' || public.market_candleobservation_canonical_price(bid_open) || '"'
    || ',"complete":"' || CASE WHEN complete THEN 'True' ELSE 'False' END || '"'
    || ',"granularity":"' || granularity || '"'
    || ',"instrument":"' || instrument_code || '"'
    || ',"timestamp":"' || CASE
         WHEN date_part('microsecond', ts AT TIME ZONE 'UTC')::int = 0
           THEN to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
         ELSE to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')
       END || '+00:00"'
    || ',"volume":"' || volume::text || '"}',
    'sha256'), 'hex')
$$;
"""

# Helper for the lineage trigger: list (in deterministic field order) the
# content fields of a NEW observation row that differ from a prior row's
# stored content. ``differing_fields`` is a derived claim in the ledger, so
# the trigger recomputes it and refuses rows whose claim does not match
# reality. The comparison mirrors market/services.py, which diffs complete,
# volume and every price field against the content the new view supersedes.
CREATE_DIFFERING_FIELDS_SQL = r"""
CREATE FUNCTION market_candleobservation_differing_fields(
    observation market_candleobservation,
    prior_complete boolean,
    prior_volume integer,
    prior_bid_open numeric,
    prior_bid_high numeric,
    prior_bid_low numeric,
    prior_bid_close numeric,
    prior_ask_open numeric,
    prior_ask_high numeric,
    prior_ask_low numeric,
    prior_ask_close numeric
) RETURNS text
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog
AS $$
DECLARE
    fields text[] := '{}';
BEGIN
    IF observation.complete IS DISTINCT FROM prior_complete THEN
        fields := array_append(fields, 'complete');
    END IF;
    IF observation.volume IS DISTINCT FROM prior_volume THEN
        fields := array_append(fields, 'volume');
    END IF;
    IF observation.ask_close IS DISTINCT FROM prior_ask_close THEN
        fields := array_append(fields, 'ask_close');
    END IF;
    IF observation.ask_high IS DISTINCT FROM prior_ask_high THEN
        fields := array_append(fields, 'ask_high');
    END IF;
    IF observation.ask_low IS DISTINCT FROM prior_ask_low THEN
        fields := array_append(fields, 'ask_low');
    END IF;
    IF observation.ask_open IS DISTINCT FROM prior_ask_open THEN
        fields := array_append(fields, 'ask_open');
    END IF;
    IF observation.bid_close IS DISTINCT FROM prior_bid_close THEN
        fields := array_append(fields, 'bid_close');
    END IF;
    IF observation.bid_high IS DISTINCT FROM prior_bid_high THEN
        fields := array_append(fields, 'bid_high');
    END IF;
    IF observation.bid_low IS DISTINCT FROM prior_bid_low THEN
        fields := array_append(fields, 'bid_low');
    END IF;
    IF observation.bid_open IS DISTINCT FROM prior_bid_open THEN
        fields := array_append(fields, 'bid_open');
    END IF;
    IF cardinality(fields) = 0 THEN
        RETURN '[]';
    END IF;
    -- Match the JSON text Django's JSONField stores (", " separators), so the
    -- text comparison below agrees with the adapter's serialization.
    RETURN '["' || array_to_string(fields, '", "') || '"]';
END;
$$;
"""

# Exact completion instant of one live candle interval, mirroring
# market/services.live_candle_completion. H1/H4 are pure UTC arithmetic; D/W
# candles close at 17:00 America/New_York (Friday for weekly), so completion is
# a wall-clock step in that zone. Unsupported granularities are rejected.
CREATE_COMPLETION_FUNCTION_SQL = r"""
CREATE FUNCTION market_candleobservation_live_completion(
    ts timestamptz,
    granularity text
) RETURNS timestamptz
LANGUAGE sql
IMMUTABLE
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

DROP_COMPLETION_FUNCTION_SQL = (
    "DROP FUNCTION IF EXISTS market_candleobservation_live_completion(timestamptz, text);"
)

# Whether frozen evidence outside the live-observation ledger references a
# candle (the mirror of market/services.candle_is_referenced). A revision that
# changes the view of such a candle is a ``conflict``; without any reference it
# is a plain ``revision``. The tables below are the only cross-app relations
# with a candle foreign key at this migration's level.
CREATE_CANDLE_REFERENCED_SQL = r"""
CREATE FUNCTION market_candleobservation_candle_is_referenced(target_candle bigint) RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.market_candleconflict WHERE existing_candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_evidencesnapshot WHERE anchor_candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_forecastresolution WHERE horizon_candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_recommendation WHERE reference_candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_recommendationresolution WHERE horizon_candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_papertradeentry WHERE candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_papertraderesult WHERE horizon_candle_id = target_candle)
       OR EXISTS (SELECT 1 FROM public.forecasts_papertraderesult WHERE exit_candle_id = target_candle)
    THEN
        RETURN TRUE;
    END IF;
    RETURN FALSE;
END;
$$;
"""

DROP_CANDLE_REFERENCED_SQL = (
    "DROP FUNCTION IF EXISTS market_candleobservation_candle_is_referenced(bigint);"
)

DROP_DIFFERING_FIELDS_SQL = (
    "DROP FUNCTION IF EXISTS market_candleobservation_differing_fields("
    "market_candleobservation, boolean, integer, numeric, numeric, numeric, "
    "numeric, numeric, numeric, numeric, numeric);"
)

CREATE_LINEAGE_VALIDATION_SQL = r"""
CREATE FUNCTION market_candleobservation_lineage_validate() RETURNS trigger AS $$
DECLARE
    candle_row record;
    run_row record;
    head_row record;
    recomputed text;
    differing text;
    expected_completion timestamptz;
BEGIN
    SELECT * INTO candle_row FROM public.market_candle WHERE id = NEW.candle_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'observation references a missing candle (candle_id=%%)', NEW.candle_id;
    END IF;
    IF candle_row.dataset_version_id IS NOT NULL THEN
        RAISE EXCEPTION 'governed candles are not observed through market_candleobservation';
    END IF;
    IF candle_row.instrument_id IS DISTINCT FROM NEW.instrument_id
       OR candle_row.granularity IS DISTINCT FROM NEW.granularity
       OR candle_row.timestamp IS DISTINCT FROM NEW.timestamp THEN
        RAISE EXCEPTION
            'observation (instrument, granularity, timestamp) must match its candle row';
    END IF;
    SELECT * INTO run_row FROM public.market_ingestionrun WHERE id = NEW.ingestion_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'observation references a missing ingestion run (ingestion_run_id=%%)',
            NEW.ingestion_run_id;
    END IF;
    IF run_row.source_id IS DISTINCT FROM NEW.source_id
       OR run_row.instrument_id IS DISTINCT FROM NEW.instrument_id
       OR run_row.granularity IS DISTINCT FROM NEW.granularity THEN
        RAISE EXCEPTION
            'observation ingestion run must match its source, instrument and granularity';
    END IF;
    IF NEW.timestamp < run_row.requested_from OR NEW.timestamp > run_row.requested_to THEN
        RAISE EXCEPTION
            'observation timestamp %% falls outside its ingestion run request window %%..%%',
            NEW.timestamp, run_row.requested_from, run_row.requested_to;
    END IF;
    IF run_row.status IN ('failed', 'quarantined') THEN
        RAISE EXCEPTION
            'observation references an ingestion run whose status is %%', run_row.status;
    END IF;
    IF run_row.requested_to < NEW.interval_end THEN
        RAISE EXCEPTION
            'observation interval_end %% extends beyond its ingestion run request window',
            NEW.interval_end;
    END IF;
    expected_completion := market_candleobservation_live_completion(
        NEW.timestamp, NEW.granularity);
    IF expected_completion IS NULL THEN
        RAISE EXCEPTION 'unsupported observation granularity %%', NEW.granularity;
    END IF;
    IF NEW.interval_end IS DISTINCT FROM expected_completion THEN
        RAISE EXCEPTION
            'observation interval_end %% does not match the %% completion %%',
            NEW.interval_end, NEW.granularity, expected_completion;
    END IF;
    -- Credible chronology: the row was observed while its run executed, so its
    -- observed_at cannot precede the run creation nor lag it by more than a
    -- day (ingestion runs are synchronous).
    IF NEW.observed_at IS NULL
       OR NEW.observed_at < run_row.started_at
       OR NEW.observed_at > run_row.started_at + interval '1 day' THEN
        RAISE EXCEPTION
            'observation observed_at %% is not contemporaneous with its run (started %%)',
            NEW.observed_at, run_row.started_at;
    END IF;
    recomputed := market_candleobservation_content_sha256(
        (SELECT code FROM public.market_instrument WHERE id = NEW.instrument_id),
        NEW.granularity, NEW.timestamp, NEW.complete, NEW.volume,
        NEW.bid_open, NEW.bid_high, NEW.bid_low, NEW.bid_close,
        NEW.ask_open, NEW.ask_high, NEW.ask_low, NEW.ask_close);
    IF recomputed IS DISTINCT FROM NEW.content_sha256 THEN
        RAISE EXCEPTION 'content_sha256 does not match the stored candle content';
    END IF;
    IF NEW.kind IN ('initial', 'late_arrival') THEN
        IF NEW.revision <> 1 OR NEW.supersedes_id IS NOT NULL THEN
            RAISE EXCEPTION
                'initial/late_arrival observations must be revision 1 with no supersedes';
        END IF;
        IF NEW.ingestion_run_id IS DISTINCT FROM candle_row.ingestion_run_id THEN
            RAISE EXCEPTION 'initial observation must belong to the run that froze its candle';
        END IF;
        IF candle_row.content_sha256 IS DISTINCT FROM NEW.content_sha256 THEN
            RAISE EXCEPTION 'initial observation content must match its frozen candle';
        END IF;
        IF EXISTS (SELECT 1 FROM public.market_candleobservation
                    WHERE candle_id = NEW.candle_id) THEN
            RAISE EXCEPTION 'initial observation requires a candle with no prior observations';
        END IF;
        IF NEW.differing_fields <> '[]'::jsonb THEN
            RAISE EXCEPTION
                'initial/late_arrival observations must record an empty differing_fields';
        END IF;
        RETURN NEW;
    END IF;
    -- kind revision/conflict: the row must continue the candle's dense chain.
    SELECT * INTO head_row FROM public.market_candleobservation
     WHERE candle_id = NEW.candle_id
     ORDER BY revision DESC, id DESC
     LIMIT 1;
    IF FOUND THEN
        IF NEW.supersedes_id IS DISTINCT FROM head_row.id
           OR NEW.revision <> head_row.revision + 1 THEN
            RAISE EXCEPTION 'revision %% must supersede revision %% of the same candle chain',
                NEW.revision, head_row.revision;
        END IF;
        IF NEW.kind NOT IN ('revision', 'conflict') THEN
            RAISE EXCEPTION 'a chain continuation must be kind revision or conflict';
        END IF;
        IF market_candleobservation_candle_is_referenced(NEW.candle_id) THEN
            IF NEW.kind <> 'conflict' THEN
                RAISE EXCEPTION
                    'a change to a referenced candle must be kind conflict, not %%', NEW.kind;
            END IF;
        ELSE
            IF NEW.kind <> 'revision' THEN
                RAISE EXCEPTION
                    'a change to an unreferenced candle must be kind revision, not %%', NEW.kind;
            END IF;
        END IF;
        differing := market_candleobservation_differing_fields(
            NEW, candle_row.complete, candle_row.volume,
            candle_row.bid_open, candle_row.bid_high, candle_row.bid_low, candle_row.bid_close,
            candle_row.ask_open, candle_row.ask_high, candle_row.ask_low, candle_row.ask_close);
        IF differing IS DISTINCT FROM NEW.differing_fields::text THEN
            RAISE EXCEPTION
                'differing_fields %% does not match the frozen candle content (%%)',
                NEW.differing_fields, differing;
        END IF;
        RETURN NEW;
    END IF;
    -- First recorded view: allowed only for a legacy candle (frozen before the
    -- observation ledger existed, so no attested content hash). It opens the
    -- chain at revision 1 and must describe this candle's content relative to
    -- the frozen row it records.
    IF candle_row.content_sha256 IS NOT NULL THEN
        RAISE EXCEPTION 'a candle with attested content cannot open an observation chain';
    END IF;
    IF NEW.revision <> 1 OR NEW.supersedes_id IS NOT NULL THEN
        RAISE EXCEPTION
            'a chain-opening revision/conflict observation must be revision 1 with no supersedes';
    END IF;
    differing := market_candleobservation_differing_fields(
        NEW, candle_row.complete, candle_row.volume,
        candle_row.bid_open, candle_row.bid_high, candle_row.bid_low, candle_row.bid_close,
        candle_row.ask_open, candle_row.ask_high, candle_row.ask_low, candle_row.ask_close);
    IF differing IS DISTINCT FROM NEW.differing_fields::text THEN
        RAISE EXCEPTION
            'differing_fields %% does not match the frozen candle content (%%)',
            NEW.differing_fields, differing;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public;
CREATE TRIGGER market_candleobservation_lineage_validate
BEFORE INSERT ON market_candleobservation
FOR EACH ROW EXECUTE FUNCTION market_candleobservation_lineage_validate();
"""

DROP_LINEAGE_VALIDATION_SQL = r"""
DROP TRIGGER IF EXISTS market_candleobservation_lineage_validate ON market_candleobservation;
DROP FUNCTION IF EXISTS market_candleobservation_lineage_validate();
"""

RENUMBER_SQL = r"""
UPDATE market_candleobservation AS observation
   SET revision = numbered.chain_revision,
       supersedes_id = numbered.previous_id
  FROM (
        SELECT id, candle_id,
               row_number() OVER (PARTITION BY candle_id ORDER BY id) AS chain_revision,
               lag(id) OVER (PARTITION BY candle_id ORDER BY id) AS previous_id
          FROM market_candleobservation
       ) AS numbered
 WHERE observation.id = numbered.id
   AND (observation.revision IS DISTINCT FROM numbered.chain_revision
        OR observation.supersedes_id IS DISTINCT FROM numbered.previous_id);
"""


def create_pgcrypto(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_PGCRYPTO_SQL)


def create_canonical_price_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(_CANONICAL_NUMERIC_FORMAT)


def drop_canonical_price_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_CANONICAL_NUMERIC_FORMAT_SQL)


def create_content_hash_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_CONTENT_HASH_SQL)


def drop_content_hash_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_CONTENT_HASH_SQL)


def create_differing_fields_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_DIFFERING_FIELDS_SQL)


def drop_differing_fields_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_DIFFERING_FIELDS_SQL)


def create_completion_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_COMPLETION_FUNCTION_SQL)


def drop_completion_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_COMPLETION_FUNCTION_SQL)


def create_candle_referenced_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_CANDLE_REFERENCED_SQL)


def drop_candle_referenced_function(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_CANDLE_REFERENCED_SQL)


def create_lineage_validation(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_LINEAGE_VALIDATION_SQL)


def drop_lineage_validation(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_LINEAGE_VALIDATION_SQL)


def renumber_observation_chains(apps, schema_editor):
    """Renumber pre-0029 chains dense per candle; never touches evidence content.

    Runs inside the migration transaction. The append-only trigger is suspended
    for the single renumber statement and recreated immediately, so the window
    is invisible outside the transaction. Preflights refuse rather than bless
    corrupt rows.
    """
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             JOIN market_candle candle ON candle.id = observation.candle_id
             WHERE candle.dataset_version_id IS NOT NULL
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 cannot renumber observations attached to governed candles"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             JOIN market_candle candle ON candle.id = observation.candle_id
             WHERE observation.instrument_id IS DISTINCT FROM candle.instrument_id
                OR observation.granularity IS DISTINCT FROM candle.granularity
                OR observation.timestamp IS DISTINCT FROM candle.timestamp
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 refuses rows whose identity does not match their candle"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             JOIN market_ingestionrun run ON run.id = observation.ingestion_run_id
             WHERE run.source_id IS DISTINCT FROM observation.source_id
                OR run.instrument_id IS DISTINCT FROM observation.instrument_id
                OR run.granularity IS DISTINCT FROM observation.granularity
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 refuses rows whose ingestion run contradicts their source"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             JOIN market_instrument instrument ON instrument.id = observation.instrument_id
             WHERE public.market_candleobservation_content_sha256(
                     instrument.code, observation.granularity, observation.timestamp,
                     observation.complete, observation.volume,
                     observation.bid_open, observation.bid_high, observation.bid_low,
                     observation.bid_close,
                     observation.ask_open, observation.ask_high, observation.ask_low,
                     observation.ask_close)
                   IS DISTINCT FROM observation.content_sha256
            """
        )
        mismatched = cursor.fetchone()[0]
        if mismatched:
            raise RuntimeError(
                "market.0029 refuses to renumber rows whose content_sha256 does not "
                f"recompute from their stored content ({mismatched} row(s))"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             JOIN market_ingestionrun run ON run.id = observation.ingestion_run_id
             WHERE observation.timestamp < run.requested_from
                OR observation.timestamp > run.requested_to
                OR run.status IN ('failed', 'quarantined')
                OR run.requested_to < observation.interval_end
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 refuses rows whose run window, status or interval "
                "contradicts their observation"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             WHERE observation.interval_end IS DISTINCT FROM
                   public.market_candleobservation_live_completion(
                       observation.timestamp, observation.granularity)
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 refuses rows whose interval_end is not the canonical "
                "completion of their interval"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             JOIN market_ingestionrun run ON run.id = observation.ingestion_run_id
             WHERE observation.observed_at IS NULL
                OR observation.observed_at < run.started_at
                OR observation.observed_at > run.started_at + interval '1 day'
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 refuses rows whose observed_at is not contemporaneous "
                "with their ingestion run"
            )
        cursor.execute(
            """
            SELECT count(*) FROM market_candleobservation observation
             WHERE observation.kind IN ('initial', 'late_arrival')
               AND observation.differing_fields <> '[]'::jsonb
            """
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "market.0029 refuses initial/late_arrival rows that record "
                "differing_fields"
            )
        cursor.execute(
            "DROP TRIGGER IF EXISTS market_candleobservation_append_only "
            "ON market_candleobservation"
        )
        cursor.execute(RENUMBER_SQL)
        # RENUMBER_SQL rewrites the self-referential supersedes foreign key, and
        # its deferred check queues trigger events for every rewritten row. The
        # subsequent ALTER TABLE ... ADD CONSTRAINT of this migration then fails
        # with ``cannot ALTER TABLE ... because it has pending trigger events``
        # on any non-empty ledger. Flush the deferred checks now, inside the
        # renumber's own lock, before any schema statement touches the table.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "CREATE TRIGGER market_candleobservation_append_only "
            "BEFORE UPDATE OR DELETE ON market_candleobservation "
            "FOR EACH ROW EXECUTE FUNCTION market_candleobservation_reject_mutation()"
        )


def refuse_reverse_with_observations(apps, schema_editor):
    """Refuse to unapply once the lineage rewrite or any observation exists."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM market_candleobservation")
        observations = cursor.fetchone()[0]
        if observations:
            raise RuntimeError(
                "market.0029 is forward-only once observations exist: "
                f"market_candleobservation holds {observations} row(s) and reversing "
                "would reopen non-dense per-source chains"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0028_live_candle_observation_identity"),
    ]

    operations = [
        migrations.RunPython(create_pgcrypto, migrations.RunPython.noop),
        migrations.RunPython(
            create_canonical_price_function, drop_canonical_price_function
        ),
        migrations.RunPython(create_content_hash_function, drop_content_hash_function),
        migrations.RunPython(
            create_completion_function, drop_completion_function
        ),
        migrations.RunPython(
            create_candle_referenced_function, drop_candle_referenced_function
        ),
        migrations.RemoveConstraint(
            model_name="candleobservation",
            name="unique_candle_observation_revision",
        ),
        migrations.RemoveConstraint(
            model_name="candleobservation",
            name="candle_observation_revision_shape",
        ),
        migrations.RunPython(renumber_observation_chains, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="candleobservation",
            constraint=models.UniqueConstraint(
                fields=("candle", "revision"),
                name="unique_candle_observation_chain",
            ),
        ),
        migrations.AddConstraint(
            model_name="candleobservation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=("initial", "late_arrival"),
                        revision=1,
                        supersedes__isnull=True,
                    )
                    | models.Q(
                        kind__in=("revision", "conflict"),
                        revision=1,
                        supersedes__isnull=True,
                    )
                    | models.Q(
                        kind__in=("revision", "conflict"),
                        revision__gt=1,
                        supersedes__isnull=False,
                    )
                ),
                name="candle_observation_revision_shape",
            ),
        ),
        migrations.RunPython(
            create_differing_fields_function, drop_differing_fields_function
        ),
        migrations.RunPython(create_lineage_validation, drop_lineage_validation),
        migrations.RunPython(migrations.RunPython.noop, refuse_reverse_with_observations),
    ]
