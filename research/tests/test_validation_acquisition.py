import copy
import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from market.oanda import OandaClient
from research.validation_acquisition import Store, canonical_pairs, chunks, fetch, practice_token


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.request = next(r for r in chunks() if r["granularity"] == "H1")
        self.candle = {
            "time": "2017-01-02T01:00:00Z",
            "complete": True,
            "volume": 27,
            "bid": {"o": "1.07", "h": "1.10", "l": "1.03", "c": "1.08"},
            "ask": {"o": "1.08", "h": "1.11", "l": "1.04", "c": "1.09"},
        }
        self.calls = []

    def client(self, candles=None, status=200):
        payload = {
            "instrument": "EUR_USD",
            "granularity": "H1",
            "candles": [self.candle] if candles is None else candles,
        }

        def handle(request):
            self.calls.append(request)
            return httpx.Response(status, json=payload, headers={"RequestID": "synthetic-1"})

        return OandaClient("synthetic-secret", transport=httpx.MockTransport(handle))

    def test_canonical_population_and_partition_complete(self):
        expected = (
            "EUR_USD",
            "GBP_USD",
            "EUR_GBP",
            "USD_CAD",
            "USD_JPY",
            "AUD_USD",
            "USD_CHF",
            "NZD_USD",
            "EUR_JPY",
            "GBP_JPY",
            "AUD_JPY",
            "AUD_CAD",
        )
        self.assertEqual(canonical_pairs(), expected)
        groups = {}
        for request in chunks():
            key = request["instrument"], request["granularity"]
            if key in groups:
                self.assertEqual(groups[key], request["start"])
            groups[key] = request["end"]
            self.assertLess(request["start"], request["end"])
            self.assertFalse(request["start"] < "2025-01-06T00:00:00+00:00" < request["end"])
        self.assertEqual(len(groups), 60)
        self.assertEqual(set(groups.values()), {"2026-09-07T00:00:00+00:00"})

    def test_real_clock_retained_readonly_endpoint_and_determinism(self):
        clock = datetime(2026, 9, 11, 15, tzinfo=UTC)
        with (
            self.client() as client,
            patch("research.validation_acquisition.datetime", wraps=datetime) as fake,
        ):
            fake.now.return_value = clock
            metadata, blob = fetch(client, self.request)
            self.assertEqual((metadata, blob), fetch(client, self.request))
        self.assertEqual(metadata["acquired_at"], clock.isoformat())
        self.assertGreater(metadata["acquired_at"], metadata["last_timestamp"])
        self.assertEqual(json.loads(gzip.decompress(blob))[0]["bid_close"], "1.08")
        for request in self.calls:
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/v3/instruments/EUR_USD/candles")
            self.assertEqual(request.url.params["price"], "BA")
            self.assertEqual(request.url.params["smooth"], "false")
        self.assertNotIn("synthetic-secret", json.dumps(metadata))

    def test_invalid_metadata_geometry_duplicates_and_boundary(self):
        for field, value in (
            ("complete", "true"),
            ("complete", False),
            ("volume", -1),
            ("time", self.request["end"]),
            ("time", "2017-01-02T01:00:00"),
        ):
            candle = copy.deepcopy(self.candle)
            candle[field] = value
            with self.subTest(field=field, value=value), self.client([candle]) as client:
                with self.assertRaises((ValueError, TypeError)):
                    fetch(client, self.request)
        for price in ("NaN", "-1", "2"):
            candle = copy.deepcopy(self.candle)
            candle["bid"]["l"] = price
            with self.client([candle]) as client, self.assertRaises(ValueError):
                fetch(client, self.request)
        with (
            self.client([self.candle, self.candle]) as client,
            self.assertRaisesRegex(ValueError, "duplicate"),
        ):
            fetch(client, self.request)

    def test_restart_idempotence_sql_immutability_lock_and_refusal(self):
        with tempfile.TemporaryDirectory() as directory, self.client() as client:
            path = Path(directory) / "data.sqlite3"
            store = Store(path)
            try:
                self.assertTrue(store.acquire(client, self.request))
                before = store.inventory()
                with self.assertRaises(BlockingIOError):
                    Store(path)
                with self.assertRaises(sqlite3.IntegrityError):
                    store.db.execute("DELETE FROM chunk")
                with self.assertRaisesRegex(ValueError, "unregistered"):
                    store.acquire(client, {**self.request, "instrument": "NOT_FX"})
            finally:
                store.close()
            store = Store(path)
            try:
                self.assertFalse(store.acquire(client, self.request))
                self.assertEqual(before, store.inventory())
                self.assertEqual(len(self.calls), 1)
            finally:
                store.close()

    def test_failure_leaves_no_partial_chunk_and_empty_count_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "data.sqlite3")
            try:
                with (
                    self.client(status=401) as client,
                    self.assertRaisesRegex(ValueError, "provider_auth"),
                ):
                    store.acquire(client, self.request)
                self.assertFalse(store.contains(self.request))
                with self.client([]) as client:
                    store.acquire(client, self.request)
                self.assertEqual(store.inventory()["chunks"][0]["rows"], 0)
            finally:
                store.close()

    def test_dotenv_only_reads_practice_token_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env"
            path.write_text(
                'IGNORED=$(exit 1)\noanda_api_key_test="example" # comment\nOANDA_ACCOUNT_ID=private\n'
            )
            self.assertEqual(practice_token(path), "example")
            path.write_text("OANDA_TOKEN=not-practice\n")
            with self.assertRaisesRegex(ValueError, "missing"):
                practice_token(path)

    def test_unaligned_from_excludes_covering_bar_and_seals_cross_boundary_values(self):
        request = next(
            r
            for r in chunks()
            if r["granularity"] == "D"
            and r["period"] == "development"
            and r["end"] == "2025-01-06T00:00:00+00:00"
        )
        # Exercise both sides in one parser fixture; Store separately refuses
        # this deliberately wider, unregistered request in its admission test.
        request = {**request, "start": "2025-01-01T00:00:00+00:00"}
        earlier, crossing = copy.deepcopy(self.candle), copy.deepcopy(self.candle)
        earlier["time"] = "2025-01-02T22:00:00Z"
        crossing["time"] = "2025-01-05T22:00:00Z"

        def handle(http_request):
            self.assertEqual(http_request.url.params["includeFirst"], "false")
            return httpx.Response(
                200,
                json={"instrument": "EUR_USD", "granularity": "D", "candles": [earlier, crossing]},
            )

        with OandaClient("synthetic-secret", transport=httpx.MockTransport(handle)) as client:
            metadata, blob = fetch(client, request)
        self.assertEqual(metadata["rows"], 1)
        self.assertEqual(metadata["period_boundary_exclusions"], ["2025-01-05T22:00:00+00:00"])
        self.assertEqual(len(json.loads(gzip.decompress(blob))), 1)
