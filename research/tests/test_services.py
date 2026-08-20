import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from forecasts.models import Forecast
from market.models import Candle, Instrument, TechnicalSnapshot
from research.models import (
    DocumentRepresentation,
    EconomicEvent,
    MacroObservation,
    MacroSeries,
    PairEvidenceSnapshot,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
    SourcePolicy,
)
from research.parsers import ParseRejected, parse_feed
from research.services import (
    capture_pair_evidence,
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


@override_settings(DEBUG=True, OANDA_TOKEN="")
class PairEvidenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def retrieval(self, policy, fetched_at, marker):
        return RawRetrieval.objects.create(
            source_policy=policy,
            url=f"https://{policy.allowed_hosts[0]}/evidence/{marker}",
            request_fingerprint=marker * 64,
            fetched_at=fetched_at,
            http_status=200,
            content_type=policy.allowed_content_types[0],
            byte_count=4,
            body_sha256=marker * 64,
            body=b"test",
            retention_decision="test",
        )

    def observation(self, series, value, period, known_at, marker):
        return MacroObservation.objects.create(
            series=series,
            retrieval=self.retrieval(series.source_policy, known_at, marker),
            observation_period=period,
            value=Decimal(value),
            normalized_value=value,
            available_at=known_at,
            vintage_at=known_at,
        )

    def test_capture_is_point_in_time_pair_scoped_deduplicated_and_read_only(self):
        instrument = Instrument.objects.get(code="USD_CAD")
        candle = (
            Candle.objects.filter(instrument=instrument, granularity="H4")
            .select_related("ingestion_run")
            .last()
        )
        technical = TechnicalSnapshot.objects.get(instrument=instrument, granularity="H4")
        cutoff = max(
            timezone.now(), candle.ingestion_run.finished_at, technical.calculated_at
        ) + timedelta(seconds=2)
        canada = MacroSeries.objects.get(code="CA_CPI_YOY")
        euro = MacroSeries.objects.get(code="EU_HICP_YOY")
        sp500 = MacroSeries.objects.get(code="GLOBAL_SP500")
        known_at = cutoff - timedelta(hours=1)
        self.observation(canada, "2.1", datetime(2026, 7, 1).date(), known_at, "a")
        self.observation(euro, "1.8", datetime(2026, 7, 1).date(), known_at, "b")
        self.observation(sp500, "6500", datetime(2026, 8, 18).date(), known_at, "c")
        self.observation(
            canada,
            "9.9",
            datetime(2026, 8, 1).date(),
            cutoff + timedelta(days=1),
            "d",
        )
        news_policy = SourcePolicy.objects.get(slug="bbc-business")
        news_retrieval = self.retrieval(news_policy, known_at, "f")
        for title, published_at, marker in (
            ("Known headline", cutoff - timedelta(minutes=30), "g"),
            ("Future-dated headline", cutoff + timedelta(minutes=30), "h"),
        ):
            document = ResearchDocument.objects.create(
                canonical_url=f"https://example.com/{marker}",
                canonical_hash=marker * 64,
                title=title,
                published_at=published_at,
                first_observed_at=known_at,
                quality=ResearchDocument.Quality.VERIFIED,
            )
            DocumentRepresentation.objects.create(
                document=document,
                retrieval=news_retrieval,
                source_item_id=marker,
                dedup_key=marker * 64,
                source_title=title,
                source_published_at=published_at,
            )
        forecast_count = Forecast.objects.count()

        first = capture_pair_evidence(instrument, now=cutoff)
        repeated = capture_pair_evidence(instrument, now=cutoff + timedelta(minutes=1))

        values = {item["series"]: item["value"] for item in first.payload["macro_and_intermarket"]}
        self.assertEqual(values["CA_CPI_YOY"], "2.1")
        self.assertEqual(values["GLOBAL_SP500"], "6500")
        self.assertNotIn("EU_HICP_YOY", values)
        self.assertEqual(
            [item["title"] for item in first.payload["recent_news"]], ["Known headline"]
        )
        self.assertEqual(first, repeated)
        self.assertTrue(first.payload["boundaries"]["read_only"])
        self.assertFalse(first.payload["boundaries"]["forecast_write_authorized"])
        self.assertEqual(Forecast.objects.count(), forecast_count)

        changed_at = cutoff + timedelta(hours=2)
        self.observation(
            sp500,
            "6510",
            datetime(2026, 8, 19).date(),
            changed_at - timedelta(minutes=1),
            "e",
        )
        changed = capture_pair_evidence(instrument, now=changed_at)
        self.assertNotEqual(changed.sha256, first.sha256)
        self.assertEqual(PairEvidenceSnapshot.objects.count(), 2)
        self.assertEqual(Forecast.objects.count(), forecast_count)
