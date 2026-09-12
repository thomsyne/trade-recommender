"""Run with PHASE55_TEST_DSN pointing only to a disposable PostgreSQL database."""

import os
import re
import unittest
import uuid
from datetime import date
from unittest.mock import patch

import psycopg

from research.validation_audit import PERIODS, QUERIES, audit, encode


class AuditContractTests(unittest.TestCase):
    def test_half_open_iso_periods(self):
        periods = [(date.fromisoformat(a), date.fromisoformat(b)) for _, a, b in PERIODS]
        self.assertEqual((periods[2][1] - periods[2][0]).days, 44 * 7)
        self.assertEqual((periods[3][1] - periods[3][0]).days, 43 * 7)
        for index in range(1, 4):
            self.assertEqual(periods[index - 1][1], periods[index][0])
            self.assertEqual(periods[index][0].weekday(), 0)

    def test_fixed_queries_do_not_project_prices_or_outputs(self):
        for query in QUERIES.values():
            self.assertTrue(query.strip().startswith(("SELECT", "WITH")))
            self.assertNotRegex(
                query.lower(), r"\b(update|delete|insert|truncate|output|actual|value)\b"
            )
            for match in re.finditer(r"c\.(?:bid|ask)_\w+", query):
                self.assertTrue(query[match.end() :].startswith(" IS NOT NULL"))
        self.assertEqual(encode({"b": 2, "a": 1}), '{"a":1,"b":2}\n')
        with self.assertRaises(TypeError):
            encode({"secret": object()})


@unittest.skipUnless(os.getenv("PHASE55_TEST_DSN"), "requires explicit disposable PostgreSQL DSN")
class AuditDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = psycopg.connect(os.environ["PHASE55_TEST_DSN"])
        self.schema = "audit_" + uuid.uuid4().hex
        self.connection.execute(f'CREATE SCHEMA "{self.schema}"')
        self.connection.execute(f'SET search_path TO "{self.schema}"')
        self.connection.execute("CREATE TABLE marker (id integer)")
        self.connection.commit()

    def tearDown(self):
        self.connection.rollback()
        self.connection.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.connection.commit()
        self.connection.close()

    def test_missing_schema_is_not_empty_coverage_and_retry_bytes_match(self):
        report = audit(self.connection, "synthetic")
        self.assertEqual(
            report["results"]["revisions:sealed_first"],
            {"status": "unavailable", "sqlstate": "42P01"},
        )
        self.assertEqual(encode(report), encode(audit(self.connection, "synthetic")))

    def test_transaction_actually_refuses_writes(self):
        with patch.dict(
            QUERIES,
            {
                "write_probe": "WITH x AS (INSERT INTO marker VALUES (7) RETURNING id) SELECT id FROM x"
            },
            clear=True,
        ):
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                audit(self.connection, "synthetic")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM marker").fetchone(), (0,))

    def test_active_transaction_refused(self):
        self.connection.execute("SELECT 1")
        with self.assertRaisesRegex(ValueError, "idle_connection"):
            audit(self.connection, "synthetic")

    def test_output_bound_does_not_claim_partial_inspection(self):
        with patch.dict(QUERIES, {"bound": "SELECT generate_series(1,501) AS id"}, clear=True):
            report = audit(self.connection, "synthetic")
        self.assertEqual(
            report["results"]["bound:all"], {"status": "unavailable", "reason": "output_bound"}
        )

    def test_period_boundaries_duplicates_gaps_and_acquisition_absence(self):
        self.connection.execute(
            "CREATE TABLE market_candle (dataset_version_id integer, instrument_id integer, "
            "granularity text, timestamp timestamptz)"
        )
        self.connection.execute(
            "INSERT INTO market_candle VALUES "
            "(1,1,'H1','2025-01-05 23:00Z'), (1,1,'H1','2025-01-06 00:00Z'),"
            "(1,1,'H1','2025-01-06 00:00Z'), (1,1,'H1','2025-01-06 03:00Z'),"
            "(1,1,'H1','2025-11-10 00:00Z')"
        )
        self.connection.commit()
        report = audit(self.connection, "synthetic")["results"]
        self.assertEqual(
            report["timestamp_discontinuities:development"]["rows"][0]["maximum_spacing_seconds"],
            None,
        )
        self.assertEqual(
            report["timestamp_discontinuities:sealed_first"]["rows"][0]["maximum_spacing_seconds"],
            10800,
        )
        self.assertEqual(
            report["timestamp_discontinuities:sealed_first"]["rows"][0]["nominal_discontinuities"],
            1,
        )
        self.assertEqual(
            report["timestamp_discontinuities:sealed_second"]["rows"][0]["nominal_discontinuities"],
            0,
        )
        self.assertEqual(report["candle_coverage:sealed_first"]["status"], "unavailable")

    def test_quote_presence_not_values_and_duplicate_counts(self):
        self.connection.execute("CREATE TABLE market_instrument (id integer,code text)")
        self.connection.execute("INSERT INTO market_instrument VALUES (1,'EUR_USD')")
        self.connection.execute("CREATE TABLE market_sourceregistry (id integer,name text)")
        self.connection.execute("INSERT INTO market_sourceregistry VALUES (1,'synthetic')")
        self.connection.execute("CREATE TABLE market_ingestionrun (id integer,source_id integer)")
        self.connection.execute("INSERT INTO market_ingestionrun VALUES (1,1)")
        self.connection.execute(
            "CREATE TABLE market_candle (dataset_version_id integer,instrument_id integer,"
            "ingestion_run_id integer,granularity text,timestamp timestamptz,"
            "bid_open integer,bid_high integer,bid_low integer,bid_close integer,"
            "ask_open integer,ask_high integer,ask_low integer,ask_close integer)"
        )
        self.connection.execute(
            "INSERT INTO market_candle VALUES "
            "(1,1,1,'H1','2025-01-06 00:00Z',17,23,5,19,18,24,6,20),"
            "(1,1,1,'H1','2025-01-06 00:00Z',17,23,5,19,18,24,6,NULL),"
            "(1,1,1,'H1','2025-01-06 03:00Z',17,23,5,19,18,24,6,20)"
        )
        self.connection.commit()
        report = audit(self.connection, "synthetic")["results"]
        row = report["legacy_candle_coverage:sealed_first"]["rows"][0]
        self.assertEqual(
            (row["rows"], row["distinct_intervals"], row["duplicate_intervals"]), (3, 2, 1)
        )
        self.assertEqual((row["bid_available"], row["ask_available"]), (3, 2))
        self.assertEqual(row["source"], "synthetic")
        self.assertEqual(report["candle_coverage:sealed_first"]["sqlstate"], "42703")
        self.assertNotIn("bid_open", row)
