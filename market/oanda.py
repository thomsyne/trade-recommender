import hashlib
import json
import re
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
    def __init__(self, message, *, failure_kind=None, provider_evidence=None):
        super().__init__(message)
        self.failure_kind = failure_kind
        self.provider_evidence = provider_evidence or {}


DISCOVERY_LIMIT_ERROR_CODES = frozenset(
    {
        "CANDLE_COUNT_EXCEEDED",
        "MAXIMUM_CANDLES_EXCEEDED",
        "MAXIMUM_RESULTS_EXCEEDED",
        "REQUEST_RANGE_TOO_LARGE",
        "TOO_MANY_CANDLES",
    }
)
DISCOVERY_LIMIT_ERROR_CATEGORIES = frozenset(
    {"CANDLE_COUNT_LIMIT", "MAXIMUM_RESULTS", "RANGE_LIMIT"}
)


def _discovery_http_failure_kind(response):
    if response.status_code in {401, 403}:
        return "auth"
    if response.status_code != 400:
        return "http"
    if len(response.content) > 4096:
        return "http"
    try:
        payload = response.json()
    except (TypeError, ValueError, UnicodeError):
        return "http"
    if type(payload) is not dict:
        return "http"

    def normalized(keys):
        for key in keys:
            value = payload.get(key)
            if (
                isinstance(value, str)
                and 0 < len(value) <= 80
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value)
            ):
                return value.upper().replace("-", "_")
        return None

    code = normalized(("errorCode", "code"))
    category = normalized(("errorCategory", "category"))
    if code in DISCOVERY_LIMIT_ERROR_CODES or category in DISCOVERY_LIMIT_ERROR_CATEGORIES:
        return "limit"
    return "http"


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
        self.environment = environment
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

        step = {
            "W": timedelta(weeks=1),
            "H1": timedelta(hours=1),
            "H4": timedelta(hours=4),
            "D": timedelta(days=1),
        }[granularity]
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
                "weeklyAlignment": "Friday",
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
            "weeklyAlignment": "Friday",
            "includeFirstAfterFirstPage": False,
            "requests": requests,
        }
        return candles, manifest

    def fetch_historical_chunk(
        self, instrument, granularity, start, end, canonical_request_sha256=None
    ):
        """Fetch one pre-registered logical chunk without prospective pagination semantics."""
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("historical chunk requires an aware increasing range")
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        params = {
            "price": "BA",
            "granularity": granularity,
            "from": _iso(start),
            "to": _iso(end),
            "smooth": "false",
            "dailyAlignment": "17",
            "alignmentTimezone": "America/New_York",
            "weeklyAlignment": "Friday",
            "includeFirst": "true",
        }
        canonical_request = {
            "instrument": instrument,
            "granularity": granularity,
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
        if canonical_request_sha256 is None:
            canonical_request_sha256 = manifest_hash(canonical_request)
        provider_evidence = {
            "endpoint_identity": (
                f"oanda-v20-{self.environment}:GET:/v3/instruments/{instrument}/candles"
            ),
            "http_method": "GET",
            "oanda_environment": self.environment,
            "canonical_request_sha256": canonical_request_sha256,
        }
        try:
            response = self.client.get(f"/instruments/{instrument}/candles", params=params)
        except httpx.HTTPError as error:
            raise OandaError(
                "OANDA historical request failed",
                failure_kind="http",
                provider_evidence={
                    **provider_evidence,
                    "unavailable_fields": ["http_status", "provider_request_id"],
                },
            ) from error
        provider_evidence = {
            **provider_evidence,
            "http_status": response.status_code,
            "provider_request_id": response.headers.get("RequestID", ""),
        }
        if not provider_evidence["provider_request_id"]:
            provider_evidence["unavailable_fields"] = ["provider_request_id"]
        if response.status_code != 200:
            kind = "auth" if response.status_code in {401, 403} else "http"
            raise OandaError(
                f"OANDA historical request returned HTTP {response.status_code}",
                failure_kind=kind,
                provider_evidence=provider_evidence,
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise OandaError(
                "OANDA historical response is malformed",
                failure_kind="malformed",
                provider_evidence=provider_evidence,
            ) from error
        try:
            candles = [_parse_candle(item) for item in payload["candles"]]
        except (KeyError, TypeError, ValueError, ArithmeticError) as error:
            raise OandaError(
                "OANDA historical response contains a malformed candle",
                failure_kind="malformed",
                provider_evidence=provider_evidence,
            ) from error
        manifest = {
            "instrument": instrument,
            "granularity": granularity,
            "from": _iso(start),
            "to": _iso(end),
            "price": "BA",
            "smooth": False,
            "alignmentTimezone": "America/New_York",
            "dailyAlignment": 17,
            "weeklyAlignment": "Friday",
            "includeFirst": True,
            "requests": [
                {
                    **provider_evidence,
                }
            ],
        }
        return candles, manifest

    def fetch_historical_inventory(self, instrument, granularity, start, end):
        """Fetch one structural inventory, discarding all price values during parsing."""
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("historical discovery requires an aware increasing range")
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        params = {
            "price": "BA",
            "granularity": granularity,
            "from": _iso(start),
            "to": _iso(end),
            "smooth": "false",
            "dailyAlignment": "17",
            "alignmentTimezone": "America/New_York",
            "weeklyAlignment": "Friday",
            "includeFirst": "true",
        }
        canonical_request = {
            "instrument": instrument,
            "granularity": granularity,
            "from": _iso(start),
            "to": _iso(end),
            "price": "BA",
            "price_component": "COMBINED_BID_ASK",
            "smooth": False,
            "dailyAlignment": 17,
            "alignmentTimezone": "America/New_York",
            "weeklyAlignment": "Friday",
            "includeFirst": True,
        }
        evidence = {
            "endpoint_identity": (
                f"oanda-v20-{self.environment}:GET:/v3/instruments/{instrument}/candles"
            ),
            "http_method": "GET",
            "oanda_environment": self.environment,
            "canonical_request_sha256": manifest_hash(canonical_request),
        }
        try:
            response = self.client.get(f"/instruments/{instrument}/candles", params=params)
        except httpx.HTTPError:
            raise OandaError(
                "OANDA discovery request failed",
                failure_kind="http",
                provider_evidence={
                    **evidence,
                    "unavailable_fields": ["http_status", "provider_request_id"],
                },
            ) from None
        evidence.update(
            http_status=response.status_code,
            provider_request_id=response.headers.get("RequestID", ""),
        )
        if not evidence["provider_request_id"]:
            evidence["unavailable_fields"] = ["provider_request_id"]
        if response.status_code != 200:
            raise OandaError(
                f"OANDA discovery request returned HTTP {response.status_code}",
                failure_kind=_discovery_http_failure_kind(response),
                provider_evidence=evidence,
            )
        try:
            candles = response.json()["candles"]
            if not isinstance(candles, list):
                raise TypeError
            from market.historical_discovery import StructuralObservation

            observations = [
                StructuralObservation(
                    timestamp=_provider_timestamp(item["time"]),
                    complete=item["complete"],
                    volume=item["volume"],
                    bid_present=_canonical_price_component(item.get("bid")),
                    ask_present=_canonical_price_component(item.get("ask")),
                )
                for item in candles
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise OandaError(
                "OANDA discovery response is malformed",
                failure_kind="malformed",
                provider_evidence=evidence,
            ) from None
        return observations, evidence

    def fetch_account_terms(self, account_id, instruments):
        if not account_id:
            raise ValueError("OANDA_ACCOUNT_ID is required")
        codes = sorted(instruments)
        summary_response = self.client.get(f"/accounts/{account_id}/summary")
        summary = _response_json(summary_response)
        instruments_response = self.client.get(
            f"/accounts/{account_id}/instruments",
            params={"instruments": ",".join(codes)},
        )
        payload = _response_json(instruments_response)
        returned = payload.get("instruments", [])
        if {item.get("name") for item in returned} != set(codes):
            raise OandaError("OANDA account instruments response was incomplete")
        return {
            "account_currency": summary.get("account", {}).get("currency"),
            "instruments": returned,
            "manifest": {
                "endpoint": "account-summary-and-instruments",
                "environment": self.environment,
                "instruments": codes,
                "summary_status": summary_response.status_code,
                "instruments_status": instruments_response.status_code,
            },
        }


def manifest_hash(manifest):
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _provider_timestamp(value):
    if not isinstance(value, str):
        raise TypeError("provider timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("provider timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_price_component(value):
    return isinstance(value, dict) and set(value) == {"o", "h", "l", "c"}


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


def _response_json(response):
    if response.status_code != 200:
        try:
            message = response.json().get("errorMessage")
        except (json.JSONDecodeError, TypeError):
            message = None
        detail = f": {message}" if message else ""
        raise OandaError(f"OANDA returned HTTP {response.status_code}{detail}")
    return response.json()


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")
