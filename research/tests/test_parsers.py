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
    def test_bank_of_canada_keeps_documented_eastern_release_time(self):
        body = b"""<rss xmlns:ev="https://example.test/events"><channel><item>
<title>Interest Rate Announcement</title><link>https://www.bankofcanada.ca/2026/09/fad-press-release/</link>
<description>Interest rate announcement at 9:45 (ET)</description>
<ev:occurrenceDate>2026-09-02</ev:occurrenceDate>
</item><item><title>Market Participants Survey</title><ev:occurrenceDate>2026-09-03</ev:occurrenceDate></item>
</channel></rss>"""
        events = parse_official_calendar("boc", body)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_at, datetime(2026, 9, 2, 13, 45, tzinfo=UTC))
        self.assertEqual(events[0].time_precision, "exact")

    def test_federal_reserve_uses_final_meeting_day_without_inventing_time(self):
        body = b"""<a>2026 FOMC Meetings</a>
<div class="fomc-meeting__month"><strong>September</strong></div>
<div class="fomc-meeting__date">15-16*</div>
<a>2025 FOMC Meetings</a>
<div class="fomc-meeting__month"><strong>August</strong></div>
<div class="fomc-meeting__date">22 (notation vote)</div>"""
        events = parse_official_calendar("fed", body)
        self.assertEqual(events[0].event_at, datetime(2026, 9, 16, tzinfo=UTC))
        self.assertEqual(events[0].time_precision, "date")

    def test_bank_of_england_and_ecb_dates_remain_date_only(self):
        boe = b"""<h2>2026 confirmed dates</h2><p>Thursday 17 September</p>"""
        ecb = b"""<dl><dt>10/09/2026</dt><dd>Monetary policy meeting, day 2</dd></dl>"""
        boe_event = parse_official_calendar("boe", boe)[0]
        ecb_event = parse_official_calendar("ecb", ecb)[0]
        self.assertEqual(boe_event.event_at, datetime(2026, 9, 17, tzinfo=UTC))
        self.assertEqual(ecb_event.event_at, datetime(2026, 9, 10, tzinfo=UTC))
        self.assertEqual(boe_event.time_precision, "date")
        self.assertEqual(ecb_event.time_precision, "date")

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
