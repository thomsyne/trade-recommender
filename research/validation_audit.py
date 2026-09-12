"""Phase5.5 metadata-only audit. No evaluator, outcome, provider or ORM imports.

Run with a psycopg connection configured by the operator. This module never loads
dotenv files or credentials and never retrieves price/result values. A missing
table/column is reported explicitly for older deployed schemas.
"""

import json
from datetime import date, datetime

PERIODS = (
    ("warmup", "2017-01-01", "2019-01-07"),
    ("development", "2019-01-07", "2025-01-06"),
    ("sealed_first", "2025-01-06", "2025-11-10"),
    ("sealed_second", "2025-11-10", "2026-09-07"),
)

# These are intentionally fixed projections, not SELECT * or manifest/output JSON.
QUERIES = {
    "instruments": """
        SELECT code, base_currency, quote_currency FROM market_instrument ORDER BY code
    """,
    "datasets": """
        SELECT d.id, d.name, d.version, s.name AS source, d.manifest_sha256,
               d.created_at FROM market_datasetversion d
        LEFT JOIN market_sourceregistry s ON s.id=d.source_id ORDER BY d.id
    """,
    "legacy_candle_coverage": """
        SELECT c.dataset_version_id, s.name AS source, i.code, c.granularity,
               min(c.timestamp) AS first_interval, max(c.timestamp) AS last_interval,
               count(*) AS rows, count(DISTINCT c.timestamp) AS distinct_intervals,
               count(*)-count(DISTINCT c.timestamp) AS duplicate_intervals,
               count(*) FILTER (WHERE c.bid_open IS NOT NULL AND c.bid_high IS NOT NULL
                   AND c.bid_low IS NOT NULL AND c.bid_close IS NOT NULL) AS bid_available,
               count(*) FILTER (WHERE c.ask_open IS NOT NULL AND c.ask_high IS NOT NULL
                   AND c.ask_low IS NOT NULL AND c.ask_close IS NOT NULL) AS ask_available
        FROM market_candle c JOIN market_instrument i ON i.id=c.instrument_id
        JOIN market_ingestionrun r ON r.id=c.ingestion_run_id
        JOIN market_sourceregistry s ON s.id=r.source_id
        WHERE c.timestamp >= %s AND c.timestamp < %s
        GROUP BY c.dataset_version_id,s.name,i.code,c.granularity
        ORDER BY c.dataset_version_id,s.name,i.code,c.granularity
    """,
    "candle_coverage": """
        SELECT c.dataset_version_id, s.name AS source, i.code, c.granularity,
               min(c.timestamp) AS first_interval, max(c.timestamp) AS last_interval,
               count(*) AS rows, count(DISTINCT c.timestamp) AS distinct_intervals,
               count(*)-count(DISTINCT c.timestamp) AS duplicate_intervals,
               min(c.observed_at) AS first_acquired, max(c.observed_at) AS last_acquired,
               count(*) FILTER (WHERE c.observed_at IS NULL) AS unknown_acquisition,
               count(*) FILTER (WHERE c.provenance='legacy_unknown') AS legacy_unknown,
               count(*) FILTER (WHERE c.provenance='fixture') AS fixtures,
               count(*) FILTER (WHERE c.bid_open IS NOT NULL AND c.bid_high IS NOT NULL
                   AND c.bid_low IS NOT NULL AND c.bid_close IS NOT NULL) AS bid_available,
               count(*) FILTER (WHERE c.ask_open IS NOT NULL AND c.ask_high IS NOT NULL
                   AND c.ask_low IS NOT NULL AND c.ask_close IS NOT NULL) AS ask_available
        FROM market_candle c JOIN market_instrument i ON i.id=c.instrument_id
        JOIN market_ingestionrun r ON r.id=c.ingestion_run_id
        JOIN market_sourceregistry s ON s.id=r.source_id
        WHERE c.timestamp >= %s AND c.timestamp < %s
        GROUP BY c.dataset_version_id,s.name,i.code,c.granularity
        ORDER BY c.dataset_version_id,s.name,i.code,c.granularity
    """,
    "timestamp_discontinuities": """
        WITH times AS (
            SELECT DISTINCT dataset_version_id,instrument_id,granularity,timestamp
            FROM market_candle WHERE timestamp >= %s AND timestamp < %s
        ), gaps AS (
            SELECT *, timestamp-lag(timestamp) OVER (
                PARTITION BY dataset_version_id,instrument_id,granularity
                ORDER BY timestamp) AS delta FROM times
        )
        SELECT dataset_version_id,instrument_id,granularity,
               count(*) FILTER (WHERE delta > CASE granularity
                   WHEN 'M15' THEN interval '15 minutes' WHEN 'H1' THEN interval '1 hour'
                   WHEN 'H4' THEN interval '4 hours' WHEN 'D' THEN interval '1 day'
                   WHEN 'W' THEN interval '7 days' END) AS nominal_discontinuities,
               max(extract(epoch FROM delta))::bigint AS maximum_spacing_seconds
        FROM gaps GROUP BY dataset_version_id,instrument_id,granularity
        ORDER BY dataset_version_id,instrument_id,granularity
    """,
    "revisions": """
        SELECT source_id,instrument_id,granularity,kind,count(*) AS rows,
               min(timestamp) AS first_interval,max(timestamp) AS last_interval,
               min(observed_at) AS first_acquired,max(observed_at) AS last_acquired,
               min(recorded_at) AS first_recorded,max(recorded_at) AS last_recorded,
               max(revision) AS maximum_revision
        FROM market_candleobservation WHERE timestamp >= %s AND timestamp < %s
        GROUP BY source_id,instrument_id,granularity,kind
        ORDER BY source_id,instrument_id,granularity,kind
    """,
    "terms": """
        SELECT instrument_id,environment,account_currency,count(*) AS rows,
               min(captured_at) AS first_acquired,max(captured_at) AS last_acquired,
               count(*) FILTER (WHERE commission_supplied) AS commission_supplied,
               count(*) FILTER (WHERE financing_days <> '[]'::jsonb) AS financing_days_present
        FROM market_oandainstrumenttermssnapshot
        GROUP BY instrument_id,environment,account_currency
        ORDER BY instrument_id,environment,account_currency
    """,
    "calendar_vintages": """
        SELECT country,time_precision,count(*) AS rows,
               min(event_at) AS first_event,max(event_at) AS last_event,
               min(first_observed_at) AS first_acquired,max(first_observed_at) AS last_acquired,
               count(*) FILTER (WHERE first_observed_at <= event_at) AS prospective_rows,
               count(*) FILTER (WHERE estimate IS NOT NULL) AS consensus_present
        FROM research_economicevent GROUP BY country,time_precision ORDER BY country,time_precision
    """,
    "macro_vintages": """
        SELECT series_id,availability_precision,count(*) AS rows,
               min(observation_period) AS first_period,max(observation_period) AS last_period,
               min(available_at) AS first_available,max(available_at) AS last_available,
               min(vintage_at) AS first_vintage,max(vintage_at) AS last_vintage,
               max(revision_sequence) AS maximum_revision
        FROM research_macroobservation GROUP BY series_id,availability_precision
        ORDER BY series_id,availability_precision
    """,
    "phase5_prior_evaluation_metadata": """
        SELECT d.strategy,d.body_sha256,count(*) AS rows,
               min(s.information_cutoff) AS first_cutoff,max(s.information_cutoff) AS last_cutoff
        FROM market_strategyevaluation e JOIN market_strategydefinition d ON d.id=e.definition_id
        JOIN market_marketstatesnapshot s ON s.id=e.snapshot_id
        WHERE s.information_cutoff >= %s AND s.information_cutoff < %s
        GROUP BY d.strategy,d.body_sha256 ORDER BY d.strategy,d.body_sha256
    """,
    "phase5_prior_simulation_metadata": """
        SELECT d.strategy,d.body_sha256,count(*) AS rows,
               min(s.information_cutoff) AS first_cutoff,max(s.information_cutoff) AS last_cutoff
        FROM market_strategysimulation x
        JOIN market_strategyevaluation e ON e.id=x.evaluation_id
        JOIN market_strategydefinition d ON d.id=e.definition_id
        JOIN market_marketstatesnapshot s ON s.id=x.outcome_snapshot_id
        WHERE s.information_cutoff >= %s AND s.information_cutoff < %s
        GROUP BY d.strategy,d.body_sha256 ORDER BY d.strategy,d.body_sha256
    """,
    "earlier_research_access": """
        SELECT detector_version,dataset_version_id,count(*) AS rows,
               min(completed_h1_timestamp) AS first_interval,
               max(completed_h1_timestamp) AS last_interval
        FROM research_analysisrun GROUP BY detector_version,dataset_version_id
        ORDER BY detector_version,dataset_version_id
    """,
}


def audit(connection, source_label):
    """Own one read-only snapshot; bounded output, statement timeout, no partial pass."""
    if connection.info.transaction_status != 0:
        raise ValueError("audit_requires_idle_connection")
    results = {}
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute("SET LOCAL lock_timeout = '2s'")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise ValueError("audit_not_read_only")
        for name, query in QUERIES.items():
            periods = PERIODS if "%s" in query else (("all", None, None),)
            for period, start, end in periods:
                key = f"{name}:{period}"
                try:
                    with connection.transaction():
                        with connection.cursor() as cursor:
                            cursor.execute(query + " LIMIT 501", (start, end) if start else None)
                            rows = cursor.fetchall()
                            if len(rows) > 500:
                                results[key] = {"status": "unavailable", "reason": "output_bound"}
                                continue
                            columns = [column.name for column in cursor.description]
                            results[key] = {
                                "status": "inspected",
                                "rows": [dict(zip(columns, row, strict=True)) for row in rows],
                            }
                except Exception as exc:
                    # Do not emit exception text: it may contain connection/provider secrets.
                    state = getattr(exc, "sqlstate", None)
                    if state not in {"42P01", "42703", "57014", "55P03", "42501"}:
                        raise
                    results[key] = {"status": "unavailable", "sqlstate": state}
    return {
        "schema": "phase5.5/coverage-audit-v1",
        "source": source_label,
        "results": results,
        "holdout": "sealed_no_outcomes_loaded",
        "prior_use": "requires_owner_attestation_and_research_history",
        "calendar_gap_classification": "unavailable_without_attested_expected_open_calendar",
        "legacy_candle_acquisition_revision_semantics": "unknown_without_observation_ledger",
        "mid": "derivable_from_BA_not_loaded_not_executable",
        "slippage_conversion_forwards_rollovers": "not_established_by_this_audit",
    }


def encode(report):
    def scalar(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError("audit_unexpected_scalar")

    return json.dumps(report, default=scalar, sort_keys=True, separators=(",", ":")) + "\n"
