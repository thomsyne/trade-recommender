"""Phase 4 slice 7 — macro/event/spread point-in-time context.

Vintage-correct reads of attested research records: event exact-vs-date-only and
availability leakage, macro revision leakage (a later revision never influences
an earlier cutoff), severity reported unavailable (never invented), and spread
from observed bid/ask. Research fixtures are built by hand.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase

from market.models import Instrument, SourceRegistry
from market.state.context import event_state, macro_regime, spread_context
from research.models import (
    EconomicEvent,
    MacroObservation,
    MacroSeries,
    RawRetrieval,
    SourcePolicy,
)

CUTOFF = datetime(2026, 2, 2, 12, 0, tzinfo=UTC)


def instrument():
    inst, _ = Instrument.objects.get_or_create(
        code="EUR_USD",
        defaults={"base_currency": "EUR", "quote_currency": "USD", "display_order": 5},
    )
    return inst


_seq = [0]


def _uniq():
    _seq[0] += 1
    return f"{_seq[0]:064d}"


def policy(jurisdiction, currency):
    src = SourceRegistry.objects.create(
        name=f"src-{jurisdiction}-{_uniq()[:6]}",
        tier="established",
        base_url="https://example.test",
        acquisition_method="m",
        retention_policy="r",
    )
    return SourcePolicy.objects.create(
        source=src,
        slug=f"pol-{jurisdiction}-{_uniq()[:6]}",
        jurisdiction=jurisdiction,
        currency=currency,
        rights_url="https://example.test/rights",
        state=SourcePolicy.State.ENABLED,
    )


def retrieval(pol, fetched_at):
    return RawRetrieval.objects.create(
        source_policy=pol,
        url="https://example.test/data",
        request_fingerprint=_uniq(),
        fetched_at=fetched_at,
        http_status=200,
        content_type="text/csv",
        byte_count=1,
        body_sha256=_uniq(),
        body=b"x",
        retention_decision="keep",
    )


def series(pol, code):
    return MacroSeries.objects.create(
        source_policy=pol,
        code=code,
        provider_series_id="p",
        label="Policy rate",
        indicator=MacroSeries.Indicator.POLICY_RATE,
        unit="%",
        frequency="monthly",
        parser=MacroSeries.Parser.FRED_CSV,
        url="https://example.test/series",
        point_in_time_note="pit",
    )


def observation(ser, pol, period, value, available_at, vintage_at, revision=0):
    return MacroObservation.objects.create(
        series=ser,
        retrieval=retrieval(pol, vintage_at),
        observation_period=period,
        value=Decimal(str(value)),
        normalized_value=str(value),
        available_at=available_at,
        vintage_at=vintage_at,
        revision_sequence=revision,
        availability_precision=MacroObservation.AvailabilityPrecision.PROVIDER,
    )


def event(pol, country, event_at, first_observed_at, *, precision="exact", key="k", fp=None):
    return EconomicEvent.objects.create(
        retrieval=retrieval(pol, first_observed_at),
        provider_event_key=key,
        event_at=event_at,
        time_precision=precision,
        country=country,
        event_type="CPI",
        payload_fingerprint=fp or _uniq(),
        first_observed_at=first_observed_at,
    )


class SpreadTests(TestCase):
    def test_spread_from_bid_ask_close(self):
        class Obs:
            bid_close = Decimal("1.1010")
            ask_close = Decimal("1.1013")

        result = spread_context(Obs(), Decimal("0.0010"))
        self.assertEqual(result["spread"], "0.000300")
        self.assertEqual(result["spread_atr"], "0.300000")


class EventStateTests(TestCase):
    def test_exact_event_has_intraday_window_date_only_does_not(self):
        us = policy("US", "USD")
        event(us, "US", CUTOFF + timedelta(days=2), CUTOFF - timedelta(days=1), key="exact")
        event(
            us,
            "US",
            CUTOFF + timedelta(days=3),
            CUTOFF - timedelta(days=1),
            precision="date",
            key="dateonly",
        )
        result = event_state(instrument(), CUTOFF)
        by_type = {
            e["intraday_risk_window"]
            if isinstance(e["intraday_risk_window"], str)
            else e["intraday_risk_window"]["reason_code"]: e
            for e in result["events"]
        }
        self.assertIn("defined", by_type)
        self.assertIn("event_time_date_only", by_type)
        # Severity is never invented.
        self.assertTrue(all(e["severity"]["state"] == "unavailable" for e in result["events"]))

    def test_event_not_yet_observed_is_excluded(self):
        us = policy("US", "USD")
        event(us, "US", CUTOFF + timedelta(days=2), CUTOFF + timedelta(days=1), key="future")
        self.assertEqual(event_state(instrument(), CUTOFF)["events"], [])

    def test_latest_vintage_known_by_cutoff_is_used(self):
        us = policy("US", "USD")
        # v1 known before cutoff schedules the event on day+2; v2 (reschedule to day+5)
        # is not observed until after the cutoff, so v1 stands.
        event(us, "US", CUTOFF + timedelta(days=2), CUTOFF - timedelta(days=2), key="e", fp="v1")
        event(us, "US", CUTOFF + timedelta(days=5), CUTOFF + timedelta(days=1), key="e", fp="v2")
        events = event_state(instrument(), CUTOFF)["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["event_at"], (CUTOFF + timedelta(days=2)).isoformat(timespec="microseconds")
        )


class MacroRegimeTests(TestCase):
    def setUp(self):
        self.us = policy("US", "USD")
        self.eu = policy("EU", "EUR")
        self.us_series = series(self.us, "US-POLICY")
        self.eu_series = series(self.eu, "EU-POLICY")

    def test_direction_and_pit_value(self):
        observation(
            self.us_series,
            self.us,
            date(2025, 12, 1),
            "4.75",
            CUTOFF - timedelta(days=40),
            CUTOFF - timedelta(days=40),
        )
        observation(
            self.us_series,
            self.us,
            date(2026, 1, 1),
            "5.00",
            CUTOFF - timedelta(days=10),
            CUTOFF - timedelta(days=10),
        )
        observation(
            self.eu_series,
            self.eu,
            date(2026, 1, 1),
            "3.00",
            CUTOFF - timedelta(days=10),
            CUTOFF - timedelta(days=10),
        )
        result = macro_regime(instrument(), CUTOFF)
        usd = result["by_currency"]["USD"]
        self.assertEqual(usd["value"], "5.000000")
        self.assertEqual(usd["direction"], "tightening")

    def test_revision_after_cutoff_is_not_used(self):
        observation(
            self.us_series,
            self.us,
            date(2026, 1, 1),
            "5.00",
            CUTOFF - timedelta(days=10),
            CUTOFF - timedelta(days=10),
            revision=0,
        )
        # A later revision to 5.25 whose vintage is after the cutoff must be ignored.
        observation(
            self.us_series,
            self.us,
            date(2026, 1, 1),
            "5.25",
            CUTOFF - timedelta(days=10),
            CUTOFF + timedelta(days=1),
            revision=1,
        )
        observation(
            self.eu_series,
            self.eu,
            date(2026, 1, 1),
            "3.00",
            CUTOFF - timedelta(days=10),
            CUTOFF - timedelta(days=10),
        )
        usd = macro_regime(instrument(), CUTOFF)["by_currency"]["USD"]
        self.assertEqual(usd["value"], "5.000000")

    def test_missing_observation_is_unavailable_not_neutral(self):
        # The US series exists but has no observation known by the cutoff, so the
        # USD side is unavailable rather than a neutral value.
        observation(
            self.eu_series,
            self.eu,
            date(2026, 1, 1),
            "3.00",
            CUTOFF - timedelta(days=10),
            CUTOFF - timedelta(days=10),
        )
        usd = macro_regime(instrument(), CUTOFF)["by_currency"]["USD"]
        self.assertEqual(usd["state"], "unavailable")
        self.assertEqual(usd["reason_code"], "macro_vintage_unavailable")
