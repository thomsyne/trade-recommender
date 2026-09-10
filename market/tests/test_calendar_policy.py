"""Public-source fixture, US profile only; not provider acquisition evidence."""

from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from market.calendar_policy import CalendarAttestation, interval_readiness

KNOWN = datetime(2026, 9, 10, 14, tzinfo=UTC)
CLOSE = datetime(2025, 12, 24, 21, 59, tzinfo=UTC)
REOPEN = datetime(2025, 12, 25, 22, 5, tzinfo=UTC)
# Source says Eastern Time: Christmas Eve close 16:59, Christmas Day reopen
# 17:05. December is EST (UTC-5). This fixture attests the closure only; it
# deliberately does not infer every other minute was open.
CHRISTMAS = CalendarAttestation(
    version="us-fx-christmas-2025-reviewed-2026-09-10",
    source_url="https://www.oanda.com/us-en/trading/holiday-trading-hours",
    profile="oanda-us-fx",
    known_at=KNOWN,
    open_intervals=(),
    closed_intervals=((CLOSE, REOPEN),),
)


class CalendarPolicyTests(SimpleTestCase):
    def check(self, start, end, **kwargs):
        return interval_readiness(start, end, profile="oanda-us-fx", as_of=KNOWN, **kwargs)

    def test_missing_attestation_and_unattested_other_profile_fail_closed(self):
        self.assertEqual(self.check(CLOSE, REOPEN), "unavailable")
        self.assertEqual(
            interval_readiness(
                CLOSE, REOPEN, profile="oanda-canada-fx", as_of=KNOWN, attestation=CHRISTMAS
            ),
            "unavailable",
        )

    def test_source_backed_holiday_and_partial_candle_are_not_normal_sessions(self):
        self.assertEqual(self.check(CLOSE, REOPEN, attestation=CHRISTMAS), "closed")
        self.assertEqual(
            self.check(
                CLOSE - timedelta(minutes=59), CLOSE + timedelta(minutes=1), attestation=CHRISTMAS
            ),
            "irregular",
        )
        self.assertEqual(
            self.check(
                REOPEN - timedelta(minutes=5), REOPEN + timedelta(minutes=10), attestation=CHRISTMAS
            ),
            "irregular",
        )

    def test_exact_boundary_does_not_overlap_but_does_not_invent_open_coverage(self):
        self.assertEqual(
            self.check(CLOSE - timedelta(minutes=15), CLOSE, attestation=CHRISTMAS),
            "unavailable",
        )
        self.assertEqual(
            self.check(REOPEN, REOPEN + timedelta(minutes=15), attestation=CHRISTMAS),
            "unavailable",
        )

    def test_later_publication_is_not_historical_knowledge(self):
        self.assertEqual(
            interval_readiness(
                CLOSE,
                REOPEN,
                profile="oanda-us-fx",
                as_of=KNOWN - timedelta(microseconds=1),
                attestation=CHRISTMAS,
            ),
            "unavailable",
        )

    def test_explicit_open_interval_is_bounded(self):
        fixture = CalendarAttestation(
            "synthetic-boundary-test",
            "https://example.invalid",
            "fixture",
            KNOWN,
            ((REOPEN, REOPEN + timedelta(minutes=30)),),
            (),
        )
        for end, expected in (
            (REOPEN + timedelta(minutes=30), "attested_open"),
            (REOPEN + timedelta(minutes=30, microseconds=1), "unavailable"),
        ):
            self.assertEqual(
                interval_readiness(
                    REOPEN, end, profile="fixture", as_of=KNOWN, attestation=fixture
                ),
                expected,
            )
