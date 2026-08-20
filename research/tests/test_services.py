import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from django.core.exceptions import ValidationError
from django.test import TestCase

from forecasts.models import Forecast
from research.models import (
    DocumentRepresentation,
    EconomicEvent,
    MacroObservation,
    MacroSeries,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
)
from research.parsers import ParseRejected, parse_feed
from research.services import (
    ingest_eodhd_calendar,
    ingest_feed,
    ingest_macro,
    ingest_official_calendar,
)
from research.tests.factories import source_policy

PUBLIC_RESOLVER = lambda _host: {"93.184.216.34"}  # noqa: E731


def response_transport(body, content_type="application/rss+xml"):
    return httpx.MockTransport(
        lambda _request: httpx.Response(200, headers={"content-type": content_type}, content=body)
    )


def rss(title="Policy decision", summary="Official release"):
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <guid>release-1</guid><link>https://official.example/releases/1?utm_source=x</link>
      <title>{title}</title><description>{summary}</description>
      <pubDate>Tue, 18 Aug 2026 14:00:00 GMT</pubDate>
    </item></channel></rss>""".encode()


class ResearchServiceTests(TestCase):
    def setUp(self):
        self.policy = source_policy()
        self.now = datetime(2026, 8, 19, 1, tzinfo=UTC)

    def test_feed_normalization_is_deterministic_and_tracks_duplicates(self):
        kwargs = {
            "transport": response_transport(rss()),
            "resolver": PUBLIC_RESOLVER,
            "now": self.now,
        }
        ingest_feed(self.policy, "https://official.example/feed", **kwargs)
        ingest_feed(self.policy, "https://official.example/feed", **kwargs)

        self.assertEqual(RawRetrieval.objects.count(), 2)
        self.assertEqual(ResearchDocument.objects.count(), 1)
        self.assertEqual(DocumentRepresentation.objects.count(), 1)
        self.assertEqual(ResearchDiscrepancy.objects.filter(kind="duplicate").count(), 0)
        self.assertEqual(
            ResearchDocument.objects.get().canonical_url, "https://official.example/releases/1"
        )

    def test_conflicting_feed_representation_is_recorded_not_overwritten(self):
        ingest_feed(
            self.policy,
            "https://official.example/feed",
            transport=response_transport(rss()),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        ingest_feed(
            self.policy,
            "https://official.example/feed",
            transport=response_transport(rss(title="Changed title")),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        document = ResearchDocument.objects.get()
        self.assertEqual(document.title, "Policy decision")
        self.assertEqual(document.quality, ResearchDocument.Quality.CONFLICT)
        self.assertTrue(ResearchDiscrepancy.objects.filter(kind="conflict").exists())

    def test_syndicated_item_preserves_both_representations(self):
        ingest_feed(
            self.policy,
            "https://official.example/feed",
            transport=response_transport(rss()),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        second = source_policy(
            name="Second official source",
            slug="second-official",
        )
        ingest_feed(
            second,
            "https://official.example/feed",
            transport=response_transport(rss()),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        self.assertEqual(ResearchDocument.objects.count(), 1)
        self.assertEqual(DocumentRepresentation.objects.count(), 2)
        self.assertEqual(ResearchDiscrepancy.objects.get().kind, "duplicate")

    def test_macro_revision_preserves_both_vintages(self):
        series = MacroSeries.objects.create(
            source_policy=self.policy,
            code="TEST_RATE",
            provider_series_id="RATE",
            label="Test rate",
            unit="percent",
            frequency="daily",
            parser=MacroSeries.Parser.FRED_CSV,
            url="https://official.example/rate.csv",
            point_in_time_note="test",
        )
        for body in (
            b"observation_date,RATE\n2026-08-18,2.25\n",
            b"observation_date,RATE\n2026-08-18,2.50\n",
        ):
            ingest_macro(
                series,
                transport=response_transport(body, "text/csv"),
                resolver=PUBLIC_RESOLVER,
                now=self.now,
            )

        observations = list(MacroObservation.objects.order_by("revision_sequence"))
        self.assertEqual([item.normalized_value for item in observations], ["2.25", "2.5"])
        self.assertEqual([item.revision_sequence for item in observations], [0, 1])
        self.assertEqual(ResearchDiscrepancy.objects.get().kind, "revision")

    def test_raw_and_normalized_evidence_reject_python_mutation(self):
        retrieval = ingest_feed(
            self.policy,
            "https://official.example/feed",
            transport=response_transport(rss()),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        retrieval.quality_reason = "rewritten"
        with self.assertRaises(ValidationError):
            retrieval.save()
        with self.assertRaises(ValidationError):
            retrieval.delete()

    def test_xml_entities_are_rejected_and_research_does_not_issue_forecasts(self):
        malicious = b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss><item>&xxe;</item></rss>'
        with self.assertRaises(ParseRejected):
            parse_feed(malicious)
        before = Forecast.objects.count()
        ingest_feed(
            self.policy,
            "https://official.example/feed",
            transport=response_transport(rss()),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        self.assertEqual(Forecast.objects.count(), before)

    def test_invalid_retrieved_feed_is_preserved_as_quarantined_raw_evidence(self):
        with self.assertRaises(ParseRejected):
            ingest_feed(
                self.policy,
                "https://official.example/feed",
                transport=response_transport(b"<rss />"),
                resolver=PUBLIC_RESOLVER,
                now=self.now,
            )
        retrieval = RawRetrieval.objects.get()
        self.assertEqual(retrieval.quality, RawRetrieval.Quality.QUARANTINED)
        self.assertEqual(ResearchDocument.objects.count(), 0)

    def test_calendar_ingestion_redacts_token_and_does_not_issue_forecasts(self):
        policy = source_policy(name="EODHD", slug="eodhd-calendar")
        policy.allowed_hosts = ["eodhd.com"]
        policy.save()
        body = b"""[{"type":"GDP Growth Rate","comparison":"qoq","period":"Q2","country":"CA","date":"2026-08-20 12:30:00","actual":1.2,"previous":0.8,"estimate":1.0}]"""
        before = Forecast.objects.count()
        retrieval = ingest_eodhd_calendar(
            policy,
            "private-token",
            transport=response_transport(body, "application/rss+xml"),
            resolver=PUBLIC_RESOLVER,
            now=self.now,
        )
        self.assertNotIn("private-token", retrieval.url)
        self.assertEqual(EconomicEvent.objects.get().actual, Decimal("1.2"))
        self.assertEqual(Forecast.objects.count(), before)

    def test_official_calendar_links_series_and_preserves_schedule_changes(self):
        self.policy.allowed_content_types = ["application/json"]
        self.policy.save()
        series = MacroSeries.objects.create(
            source_policy=self.policy,
            code="CA_CPI_YOY",
            provider_series_id="CPI",
            label="CPI inflation",
            unit="percent",
            frequency="monthly",
            parser=MacroSeries.Parser.STATCAN_WDS,
            url="https://official.example/cpi",
            point_in_time_note="test",
        )
        before = Forecast.objects.count()
        for date in ("2026-08-24 00:00:01", "2026-08-25 00:00:01"):
            body = json.dumps(
                [
                    {
                        "date": date,
                        "title": "Consumer Price Index",
                        "description": "July 2026",
                        "url": "/daily/cpi",
                    }
                ]
            ).encode()
            ingest_official_calendar(
                self.policy,
                "statcan",
                "https://official.example/calendar.json",
                transport=response_transport(body, "application/json"),
                resolver=PUBLIC_RESOLVER,
                now=self.now,
            )

        events = list(EconomicEvent.objects.order_by("event_at"))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].series, series)
        self.assertEqual(events[0].event_at, datetime(2026, 8, 24, 12, 30, tzinfo=UTC))
        self.assertEqual(events[0].source_url, "https://www150.statcan.gc.ca/n1/daily/cpi")
        self.assertIsNone(events[0].estimate)
        self.assertEqual(events[0].provider_event_key, events[1].provider_event_key)
        self.assertNotEqual(events[0].payload_fingerprint, events[1].payload_fingerprint)
        self.assertEqual(Forecast.objects.count(), before)

    def test_eurostat_regenerated_ics_uids_do_not_duplicate_events(self):
        self.policy.allowed_content_types = ["text/plain"]
        self.policy.save()
        MacroSeries.objects.create(
            source_policy=self.policy,
            code="EU_HICP_YOY",
            provider_series_id="HICP",
            label="HICP inflation",
            unit="percent",
            frequency="monthly",
            parser=MacroSeries.Parser.EUROSTAT_JSON,
            url="https://official.example/hicp",
            point_in_time_note="test",
        )
        for uid in ("generated-1", "generated-2"):
            body = f"""BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20260901\r
SUMMARY:Flash estimate inflation euro area\r
UID:{uid}\r
END:VEVENT\r
END:VCALENDAR\r
""".encode()
            ingest_official_calendar(
                self.policy,
                "eurostat",
                "https://official.example/calendar.ics",
                transport=response_transport(body, "text/plain"),
                resolver=PUBLIC_RESOLVER,
                now=self.now,
            )

        self.assertEqual(EconomicEvent.objects.count(), 1)
        self.assertEqual(RawRetrieval.objects.count(), 2)
