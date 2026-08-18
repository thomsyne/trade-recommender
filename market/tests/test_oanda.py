from datetime import UTC, datetime, timedelta

import httpx
from django.test import SimpleTestCase

from market.oanda import OandaClient


class OandaClientTests(SimpleTestCase):
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


def _payload(timestamp, complete):
    prices = {"o": "1.1000", "h": "1.1020", "l": "1.0990", "c": "1.1010"}
    ask = {key: str(float(value) + 0.0002) for key, value in prices.items()}
    return {"time": timestamp, "complete": complete, "volume": 10, "bid": prices, "ask": ask}
