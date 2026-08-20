import json
from datetime import UTC, datetime
from types import SimpleNamespace

from django.test import SimpleTestCase

from research.models import MacroSeries
from research.parsers import parse_macro, parse_official_calendar


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


class CalendarParserTests(SimpleTestCase):
    def test_eurostat_date_only_event_does_not_invent_release_time(self):
        body = b"""BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20260901\r
SUMMARY:Flash estimate inflation euro area\r
UID:inflation-2026-09\r
END:VEVENT\r
END:VCALENDAR\r
"""
        event = parse_official_calendar("eurostat", body)[0]
        self.assertEqual(event.event_at, datetime(2026, 9, 1, tzinfo=UTC))
        self.assertEqual(event.time_precision, "date")
        self.assertEqual(event.series_code, "EU_HICP_YOY")
        self.assertEqual(event.provider_event_key, "Flash estimate inflation euro area|20260901")

    def test_ons_keeps_primary_release_and_omits_time_series_duplicate(self):
        body = b"""<rss><channel>
<item><title>Consumer price inflation, UK: July 2026</title><link>https://www.ons.gov.uk/releases/cpi</link><guid>cpi</guid><pubDate>Wed, 19 Aug 2026 07:00:00 +0000</pubDate></item>
<item><title>Consumer price inflation, UK: July 2026 time series</title><link>https://www.ons.gov.uk/releases/cpi-ts</link><guid>cpi-ts</guid><pubDate>Wed, 19 Aug 2026 07:00:00 +0000</pubDate></item>
</channel></rss>"""
        events = parse_official_calendar("ons", body)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].provider_event_key, "cpi")
