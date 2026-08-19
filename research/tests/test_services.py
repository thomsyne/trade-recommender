from datetime import UTC, datetime

import httpx
from django.core.exceptions import ValidationError
from django.test import TestCase

from forecasts.models import Forecast
from research.models import (
    DocumentRepresentation,
    MacroObservation,
    MacroSeries,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
)
from research.parsers import ParseRejected, parse_feed
from research.services import ingest_feed, ingest_macro
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
