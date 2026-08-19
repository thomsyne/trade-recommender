import json
from datetime import UTC, datetime
from types import SimpleNamespace

from django.test import SimpleTestCase

from research.models import MacroSeries
from research.parsers import parse_macro


def series(parser, provider_series_id, transformation=MacroSeries.Transformation.NONE):
    return SimpleNamespace(
        parser=parser,
        provider_series_id=provider_series_id,
        transformation=transformation,
    )


class MacroParserTests(SimpleTestCase):
    def test_statcan_preserves_exact_release_time_and_status(self):
        payload = [
            {
                "status": "SUCCESS",
                "object": {
                    "vectorId": 2062815,
                    "vectorDataPoint": [
                        {
                            "refPer": "2026-07-01",
                            "value": 6.4,
                            "releaseTime": "2026-08-07T08:30",
                            "statusCode": 1,
                            "symbolCode": 0,
                        }
                    ],
                },
            }
        ]
        value = parse_macro(
            series(MacroSeries.Parser.STATCAN_WDS, "2062815"), json.dumps(payload).encode()
        )[0]
        self.assertEqual(value.available_at, datetime(2026, 8, 7, 12, 30, tzinfo=UTC))
        self.assertEqual(value.provider_status, "status=1; symbol=0")

    def test_bls_skips_provider_missing_marker_and_calculates_yoy(self):
        rows = [
            {"year": "2026", "period": "M01", "value": "110", "footnotes": [{}]},
            {"year": "2025", "period": "M10", "value": "-", "footnotes": [{}]},
            {"year": "2025", "period": "M01", "value": "100", "footnotes": [{}]},
        ]
        payload = {
            "status": "REQUEST_SUCCEEDED",
            "Results": {"series": [{"seriesID": "CPI", "data": rows}]},
        }
        values = parse_macro(
            series(
                MacroSeries.Parser.BLS_JSON,
                "CPI",
                MacroSeries.Transformation.YEAR_OVER_YEAR,
            ),
            json.dumps(payload).encode(),
        )
        self.assertEqual(values[0].normalized_value, "10")

    def test_eurostat_parses_quarters_and_dataset_update_status(self):
        payload = {
            "updated": "2026-08-14T09:00:00+00:00",
            "dimension": {"time": {"category": {"index": {"2026-Q1": 0}}}},
            "value": {"0": 0.4},
            "status": {"0": "e"},
        }
        value = parse_macro(
            series(MacroSeries.Parser.EUROSTAT_JSON, "gdp"), json.dumps(payload).encode()
        )[0]
        self.assertEqual(value.period.isoformat(), "2026-01-01")
        self.assertEqual(value.provider_status, "e")
        self.assertEqual(value.available_at, datetime(2026, 8, 14, 9, tzinfo=UTC))
