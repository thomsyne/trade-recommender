from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
from django.test import SimpleTestCase

from market.historical_acquisition import _validate_chunk_response
from market.oanda import OandaClient, OandaError, manifest_hash
from market.quality import (
    expected_candle_timestamps,
    registered_candle_completion,
    registered_successor,
)
from market.services import DatasetQualityError
from market.tests.factories import candle


class OandaClientTests(SimpleTestCase):
    def test_rejects_unknown_environment_instead_of_falling_through_to_live(self):
        with self.assertRaisesMessage(ValueError, "OANDA_ENVIRONMENT must be 'practice' or 'live'"):
            OandaClient("test-token", environment="practise")

    def test_api_error_includes_safe_oanda_message(self):
        def handler(request):
            return httpx.Response(
                401,
                json={"errorMessage": "Insufficient authorization to perform request."},
            )

        client = OandaClient("test-token", transport=httpx.MockTransport(handler))
        with self.assertRaisesMessage(
            OandaError,
            "OANDA returned HTTP 401: Insufficient authorization to perform request.",
        ):
            client.fetch_candles(
                "USD_CAD",
                "H4",
                datetime(2026, 1, 5, tzinfo=UTC),
                datetime(2026, 1, 6, tzinfo=UTC),
            )

    def test_requests_unsmoothed_bid_ask_complete_candles_with_new_york_alignment(self):
        def handler(request):
            self.assertEqual(request.url.params["price"], "BA")
            self.assertEqual(request.url.params["smooth"], "false")
            self.assertEqual(request.url.params["alignmentTimezone"], "America/New_York")
            self.assertEqual(request.url.params["dailyAlignment"], "17")
            self.assertEqual(request.headers["Authorization"], "Bearer test-token")
            body = {
                "candles": [
                    _payload("2026-01-05T21:00:00Z", complete=True),
                    _payload("2026-01-06T21:00:00Z", complete=False),
                ]
            }
            return httpx.Response(200, json=body)

        client = OandaClient("test-token", transport=httpx.MockTransport(handler))
        candles, manifest = client.fetch_candles(
            "USD_CAD",
            "D",
            datetime(2026, 1, 5, tzinfo=UTC),
            datetime(2026, 1, 7, tzinfo=UTC),
        )

        self.assertEqual(len(candles), 1)
        self.assertTrue(candles[0].complete)
        self.assertEqual(manifest["price"], "BA")
        self.assertFalse(manifest["smooth"])

    def test_later_pagination_windows_exclude_the_shared_boundary(self):
        include_first_values = []

        def handler(request):
            include_first_values.append(request.url.params["includeFirst"])
            return httpx.Response(200, json={"candles": []})

        client = OandaClient("test-token", transport=httpx.MockTransport(handler))
        start = datetime(2000, 1, 1, tzinfo=UTC)
        client.fetch_candles("USD_CAD", "D", start, start + timedelta(days=5001))

        self.assertEqual(include_first_values, ["true", "false"])

    def test_weekly_requests_use_friday_new_york_alignment(self):
        def handler(request):
            self.assertEqual(request.url.params["weeklyAlignment"], "Friday")
            self.assertEqual(request.url.params["dailyAlignment"], "17")
            self.assertEqual(request.url.params["alignmentTimezone"], "America/New_York")
            return httpx.Response(200, json={"candles": []})

        client = OandaClient("test-token", transport=httpx.MockTransport(handler))
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles, manifest = client.fetch_candles("AUD_USD", "W", start, start + timedelta(weeks=2))

        self.assertEqual(candles, [])
        self.assertEqual(manifest["weeklyAlignment"], "Friday")

    def test_historical_4999_market_candle_chunk_is_one_exact_request(self):
        start = datetime(2017, 12, 3, 22, tzinfo=UTC)
        timestamps = [start]
        while len(timestamps) < 4999:
            timestamps.append(registered_successor(timestamps[-1], "H1"))
        timestamps = tuple(timestamps)
        end = registered_candle_completion(timestamps[-1], "H1")
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.params["from"], start.isoformat().replace("+00:00", "Z"))
            self.assertEqual(request.url.params["to"], end.isoformat().replace("+00:00", "Z"))
            self.assertEqual(request.url.params["includeFirst"], "true")
            self.assertEqual(request.url.params["price"], "BA")
            self.assertEqual(request.url.params["smooth"], "false")
            self.assertEqual(request.url.params["dailyAlignment"], "17")
            self.assertEqual(request.url.params["alignmentTimezone"], "America/New_York")
            self.assertEqual(request.url.params["weeklyAlignment"], "Friday")
            return httpx.Response(
                200,
                headers={"RequestID": "provider-request-4999"},
                json={
                    "candles": [
                        _payload(timestamp.isoformat().replace("+00:00", "Z"), complete=True)
                        for timestamp in timestamps
                    ]
                },
            )

        client = OandaClient("test-token", transport=httpx.MockTransport(handler))
        candles, manifest = client.fetch_historical_chunk("EUR_USD", "H1", start, end)
        chunk = SimpleNamespace(
            instrument=SimpleNamespace(code="EUR_USD"),
            granularity="H1",
            requested_from=start,
            requested_to=end,
        )
        _validate_chunk_response(chunk, candles, manifest)

        self.assertEqual(len(requests), 1)
        self.assertEqual(len(candles), 4999)
        self.assertEqual(candles[0].timestamp, start)
        self.assertEqual(candles[-1].timestamp, timestamps[-1])
        self.assertEqual(len({item.timestamp for item in candles}), 4999)
        canonical_request_sha256 = manifest_hash(
            {
                "instrument": "EUR_USD",
                "granularity": "H1",
                "from": start.isoformat(),
                "to": end.isoformat(),
                "price": "BA",
                "price_component": "COMBINED_BID_ASK",
                "smooth": False,
                "dailyAlignment": 17,
                "alignmentTimezone": "America/New_York",
                "weeklyAlignment": "Friday",
                "includeFirst": True,
                "complete_only": True,
            }
        )
        self.assertEqual(
            manifest["requests"],
            [
                {
                    "endpoint_identity": ("oanda-v20-practice:GET:/v3/instruments/EUR_USD/candles"),
                    "http_method": "GET",
                    "oanda_environment": "practice",
                    "canonical_request_sha256": canonical_request_sha256,
                    "provider_request_id": "provider-request-4999",
                    "http_status": 200,
                }
            ],
        )

    def test_historical_response_rejects_missing_duplicate_incomplete_crossed_and_misaligned(self):
        start = datetime(2018, 12, 30, 22, tzinfo=UTC)
        end = start + timedelta(hours=2)
        expected = expected_candle_timestamps(start, end, "H1")
        manifest = {
            "instrument": "EUR_USD",
            "granularity": "H1",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "price": "BA",
            "smooth": False,
            "alignmentTimezone": "America/New_York",
            "dailyAlignment": 17,
            "weeklyAlignment": "Friday",
            "includeFirst": True,
        }
        chunk = SimpleNamespace(
            instrument=SimpleNamespace(code="EUR_USD"),
            granularity="H1",
            requested_from=start,
            requested_to=end,
        )
        valid = [candle(timestamp) for timestamp in expected]
        cases = {
            "missing": valid[:1],
            "duplicate": [valid[0], valid[0]],
            "incomplete": [valid[0], candle(expected[1], complete=False)],
            "crossed": [
                valid[0],
                candle(expected[1], bid_open=Decimal("2"), ask_open=Decimal("1")),
            ],
            "misaligned": [candle(start + timedelta(minutes=1)), valid[1]],
        }
        for name, candles in cases.items():
            with self.subTest(name=name), self.assertRaises(DatasetQualityError):
                _validate_chunk_response(chunk, candles, manifest)

    def test_fetches_account_terms_without_account_id_in_manifest(self):
        def handler(request):
            if request.url.path.endswith("/summary"):
                return httpx.Response(200, json={"account": {"currency": "CAD"}})
            return httpx.Response(
                200,
                json={
                    "instruments": [
                        {
                            "name": "USD_CAD",
                            "marginRate": "0.02",
                            "pipLocation": -4,
                            "financing": {
                                "longRate": "-0.02",
                                "shortRate": "0.01",
                                "financingDaysOfWeek": [
                                    {"dayOfWeek": "WEDNESDAY", "daysCharged": 3}
                                ],
                            },
                        }
                    ]
                },
            )

        client = OandaClient("test-token", transport=httpx.MockTransport(handler))
        payload = client.fetch_account_terms("private-account-id", ["USD_CAD"])

        self.assertEqual(payload["account_currency"], "CAD")
        self.assertEqual(payload["instruments"][0]["financing"]["longRate"], "-0.02")
        self.assertNotIn("private-account-id", str(payload["manifest"]))


def _payload(timestamp, complete):
    prices = {"o": "1.1000", "h": "1.1020", "l": "1.0990", "c": "1.1010"}
    ask = {key: str(float(value) + 0.0002) for key, value in prices.items()}
    return {"time": timestamp, "complete": complete, "volume": 10, "bid": prices, "ask": ask}
