import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx


@dataclass(frozen=True)
class CandleData:
    timestamp: datetime
    complete: bool
    volume: int
    bid_open: Decimal
    bid_high: Decimal
    bid_low: Decimal
    bid_close: Decimal
    ask_open: Decimal
    ask_high: Decimal
    ask_low: Decimal
    ask_close: Decimal


class OandaError(RuntimeError):
    pass


class OandaClient:
    def __init__(self, token, environment="practice", transport=None):
        if not token:
            raise ValueError("OANDA_TOKEN is required")
        hosts = {
            "practice": "api-fxpractice.oanda.com",
            "live": "api-fxtrade.oanda.com",
        }
        if environment not in hosts:
            raise ValueError("OANDA_ENVIRONMENT must be 'practice' or 'live'")
        self.client = httpx.Client(
            base_url=f"https://{hosts[environment]}/v3",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30),
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.client.close()

    def fetch_candles(self, instrument, granularity, start, end):
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if start >= end:
            raise ValueError("start must be before end")

        step = {"H4": timedelta(hours=4), "D": timedelta(days=1)}[granularity]
        window = step * 4999
        cursor = start.astimezone(UTC)
        end = end.astimezone(UTC)
        candles, requests = [], []
        first_request = True
        while cursor < end:
            window_end = min(cursor + window, end)
            params = {
                "price": "BA",
                "granularity": granularity,
                "from": _iso(cursor),
                "to": _iso(window_end),
                "smooth": "false",
                "dailyAlignment": "17",
                "alignmentTimezone": "America/New_York",
                "includeFirst": "true" if first_request else "false",
            }
            response = self.client.get(f"/instruments/{instrument}/candles", params=params)
            requests.append({"url": str(response.request.url), "status": response.status_code})
            if response.status_code != 200:
                try:
                    message = response.json().get("errorMessage")
                except (json.JSONDecodeError, TypeError):
                    message = None
                detail = f": {message}" if message else ""
                raise OandaError(f"OANDA returned HTTP {response.status_code}{detail}")
            candles.extend(
                parsed
                for parsed in (_parse_candle(item) for item in response.json().get("candles", []))
                if parsed.complete
            )
            cursor = window_end
            first_request = False
        manifest = {
            "instrument": instrument,
            "granularity": granularity,
            "from": _iso(start.astimezone(UTC)),
            "to": _iso(end),
            "price": "BA",
            "smooth": False,
            "alignmentTimezone": "America/New_York",
            "dailyAlignment": 17,
            "includeFirstAfterFirstPage": False,
            "requests": requests,
        }
        return candles, manifest


def manifest_hash(manifest):
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_candle(item):
    bid, ask = item["bid"], item["ask"]
    return CandleData(
        timestamp=datetime.fromisoformat(item["time"].replace("Z", "+00:00")).astimezone(UTC),
        complete=bool(item["complete"]),
        volume=int(item["volume"]),
        bid_open=Decimal(bid["o"]),
        bid_high=Decimal(bid["h"]),
        bid_low=Decimal(bid["l"]),
        bid_close=Decimal(bid["c"]),
        ask_open=Decimal(ask["o"]),
        ask_high=Decimal(ask["h"]),
        ask_low=Decimal(ask["l"]),
        ask_close=Decimal(ask["c"]),
    )


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")
