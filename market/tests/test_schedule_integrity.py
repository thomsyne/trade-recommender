"""Bounded schedule identity and exact recurrence regressions."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, models
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from market.live_schedules import duplicate_schedule_errors, validate_live_schedules
from operations.models import ScheduledJob


class Query(list):
    def iterator(self, **kwargs):
        return iter(self)

    def order_by(self, *args):
        return self


def job(pk, code="USD_JPY", granularity="H1", **overrides):
    from market.live_acquisition import LIVE_INTERVALS

    return SimpleNamespace(
        **{
            "pk": pk,
            "name": f"OANDA {code} {granularity}",
            "task_name": "market.ingest_oanda",
            "parameters": {"instrument": code, "granularity": granularity},
            "enabled": True,
            "interval_seconds": LIVE_INTERVALS[granularity],
            "schedule_type": "interval",
            "missed_run_policy": "latest",
            "timezone_name": "UTC",
            "local_time": None,
            "next_run_at": datetime(2026, 1, 1, tzinfo=UTC),
            **overrides,
        }
    )


def validate(jobs):
    instruments = {c: SimpleNamespace(ingestion_enabled=True) for c in ("USD_JPY", "AUD_USD")}
    with patch("market.live_schedules.ScheduledJob.objects.filter", return_value=Query(jobs)):
        return validate_live_schedules(instruments, provider_available=True)


class OriginalReproductions(SimpleTestCase):
    def test_unhashable_identity_emits_safe_error(self):
        _, _, errors = validate(
            [job(1, parameters={"instrument": "USD_JPY", "granularity": ["H1"]})]
        )
        self.assertTrue(any("wrong_type" in e for e in errors))

    def test_unknown_aliases_do_not_echo_raw_values(self):
        secret = "secret-control-\n\x1bΩ" + "x" * 20000
        jobs = [job(i, parameters={"instrument": secret, "granularity": "H1"}) for i in (1, 2)]
        with patch("market.live_schedules.ScheduledJob.objects.filter", return_value=Query(jobs)):
            errors = duplicate_schedule_errors()
        self.assertTrue(errors)
        self.assertNotIn(secret, " ".join(errors))
        self.assertLess(len(" ".join(errors)), 1000)

    def test_different_deadlines_collide_later(self):
        first = job(1)
        second = job(2, "AUD_USD", "H4", next_run_at=first.next_run_at + timedelta(hours=1))
        _, issues, _ = validate([first, second])
        self.assertTrue(any("collision" in e for e in issues["USD_JPY", "H1"]))


class IdentityContractTests(SimpleTestCase):
    def test_adversarial_matrix(self):
        from market.live_schedules import parse_schedule_identity

        cases = [
            (None, "malformed_parameter_container"),
            ([], "malformed_parameter_container"),
            ("secret", "malformed_parameter_container"),
            ({"granularity": "H1"}, "missing_instrument"),
            ({"instrument": "USD_JPY"}, "missing_granularity"),
        ]
        for field in ("instrument", "granularity"):
            for value in ([], {}, 1, True, None):
                cases.append(
                    (
                        {"instrument": "USD_JPY", "granularity": "H1", field: value},
                        f"wrong_type_{field}",
                    )
                )
            for value in ("unknown", "Ω\n\x1bSECRET" + "x" * 20014):
                cases.append(
                    (
                        {"instrument": "USD_JPY", "granularity": "H1", field: value},
                        f"unsupported_{field}",
                    )
                )
        cases.append(
            (
                {"instrument": "USD_JPY", "granularity": "H1", "secret-extra": "secret"},
                "unexpected_extra_parameter",
            )
        )
        for parameters, expected in cases:
            with self.subTest(reason=expected):
                identity, reasons = parse_schedule_identity(parameters)
                self.assertIsNone(identity)
                self.assertEqual(reasons, (expected,))
        self.assertEqual(
            parse_schedule_identity({}), (None, ("missing_instrument", "missing_granularity"))
        )

    def test_all_canonical_identities(self):
        from market.live_acquisition import LIVE_INTERVALS
        from market.live_schedules import parse_schedule_identity
        from market.models import Instrument

        for code in Instrument.Code.values:
            for granularity in LIVE_INTERVALS:
                self.assertEqual(
                    parse_schedule_identity({"instrument": code, "granularity": granularity}),
                    ((code, granularity), ()),
                )

    def test_bounded_inventory_order_and_duplicates(self):
        from market.live_schedules import MAX_IDENTITY_DETAILS

        jobs = [
            job(i, parameters={"instrument": "SECRET" * 5000, "granularity": {}})
            for i in range(1, MAX_IDENTITY_DETAILS + 14)
        ]
        jobs += [job(1000), job(1001, name="secret alias")]
        results = []
        for ordered in (jobs, list(reversed(jobs))):
            with patch(
                "market.live_schedules.ScheduledJob.objects.filter", return_value=Query(ordered)
            ):
                errors = duplicate_schedule_errors()
            results.append((list(errors), errors.identity_report))
            self.assertEqual(errors.identity_report["total"], MAX_IDENTITY_DETAILS + 13)
            self.assertEqual(errors.identity_report["omitted"], 13)
            self.assertEqual(len(errors.identity_report["details"]), MAX_IDENTITY_DETAILS)
            self.assertNotIn("SECRET", " ".join(errors))
            self.assertLess(len(" ".join(errors)), 10000)
            self.assertTrue(any("duplicate semantic" in e for e in errors))
        self.assertEqual(*results)


class RecurrenceTests(SimpleTestCase):
    def test_mathematical_phase_matrix(self):
        # Expected values follow divisibility by 3600, 14400 or 86400 seconds,
        # independently of any implementation helper or simulated horizon.
        from datetime import timezone

        cases = [
            ("H1", "H1", timedelta(0), True),
            ("H1", "H1", timedelta(minutes=5), False),
            ("H1", "H4", timedelta(hours=1), True),
            ("H1", "H4", timedelta(minutes=5), False),
            ("H4", "D", timedelta(hours=4), True),
            ("D", "W", timedelta(days=1), True),
            ("H1", "H4", timedelta(days=100), True),
            ("D", "W", timedelta(days=200, microseconds=1), False),
        ]
        for ga, gb, offset, expected in cases:
            with self.subTest(ga=ga, gb=gb, offset=offset):
                first = job(1, granularity=ga)
                second = job(2, "AUD_USD", gb, next_run_at=first.next_run_at + offset)
                results = []
                for jobs in ([first, second], [second, first]):
                    _, issues, errors = validate(jobs)
                    collisions = [e for e in errors if "recurring_collision" in e]
                    self.assertEqual(len(collisions), int(expected))
                    results.append((dict(issues), list(errors)))
                self.assertEqual(*results)
        first, second = job(1), job(2, "AUD_USD")
        second.next_run_at = first.next_run_at.astimezone(timezone(timedelta(hours=5, minutes=30)))
        self.assertEqual(
            len([e for e in validate([first, second])[2] if "recurring_collision" in e]), 1
        )

    def test_invalid_deadlines_and_intervals_are_conservative(self):
        for value in (None, "secret", [], {}, datetime(2026, 1, 1)):
            _, issues, _ = validate([job(1, next_run_at=value)])
            self.assertTrue(any("invalid_deadline" in e for e in issues["USD_JPY", "H1"]))
        for value in (0, -1, True, "secret", None):
            _, issues, _ = validate([job(1, interval_seconds=value)])
            self.assertTrue(any("invalid_recurrence" in e for e in issues["USD_JPY", "H1"]))

    def test_disabled_other_task_and_malformed_ignored_for_collisions(self):
        for changes in ({"enabled": False}, {"task_name": "other"}, {"parameters": []}):
            _, _, errors = validate([job(1), job(2, "AUD_USD", **changes)])
            self.assertFalse(any("recurring_collision" in e for e in errors))
        _, issues, errors = validate(
            [job(1), job(2, "AUD_USD"), job(3, name="alias", parameters=[])]
        )
        self.assertEqual(len([e for e in errors if "recurring_collision" in e]), 1)
        self.assertTrue(any("malformed_parameter_container" in e for e in errors))

    def test_lossless_epoch_conversion(self):
        from market.live_schedules import deadline_microseconds

        self.assertEqual(deadline_microseconds(datetime(1970, 1, 1, tzinfo=UTC)), 0)
        self.assertEqual(deadline_microseconds(datetime(1969, 12, 31, 23, 59, 59, 999999, UTC)), -1)
        self.assertEqual(deadline_microseconds(datetime(1970, 1, 2, 0, 0, 0, 1, UTC)), 86400000001)


@override_settings(
    OANDA_TOKEN="mock-only", OANDA_ACCOUNT_ID="", ANTHROPIC_API_KEY="", EODHD_API_TOKEN=""
)
class ScheduleReportTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        with patch("django.utils.timezone.now", return_value=self.now):
            call_command("seed_canonical", stdout=StringIO())

    def report(self, failure=True):
        output = StringIO()
        with (
            patch("django.utils.timezone.now", return_value=self.now),
            CaptureQueriesContext(connection) as queries,
        ):
            if failure:
                with self.assertRaises(CommandError):
                    call_command("report_fx_onboarding", stdout=output)
            else:
                call_command("report_fx_onboarding", stdout=output)
        self.assertEqual(
            [q["sql"] for q in queries if not q["sql"].lstrip().startswith(("SELECT", "DECLARE"))],
            [],
        )
        return output.getvalue(), json.loads(output.getvalue())

    def test_malformed_json_containers_and_types_report_and_seed_fail_closed(self):
        row = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        cases = [None, [], "SECRET\nΩ", {}, {"instrument": "USD_JPY"}, {"granularity": "H1"}]
        for field in ("instrument", "granularity"):
            for value in ([], {}, 1, True, None, "SECRET\nΩ" + "x" * 20014):
                cases.append({"instrument": "USD_JPY", "granularity": "H1", field: value})
        cases.append({"instrument": "USD_JPY", "granularity": "H1", "SECRET-KEY": "SECRET"})
        for parameters in cases:
            ScheduledJob.objects.filter(pk=row.pk).update(
                parameters=models.Value(parameters, output_field=models.JSONField())
            )
            before = list(ScheduledJob.objects.order_by("pk").values())
            text, report = self.report()
            self.assertEqual(report["schedule_identity_issues"]["total"], 1)
            self.assertNotIn("SECRET", text)
            self.assertLess(len(text), 150000)
            with self.assertRaises(CommandError) as error:
                call_command("seed_canonical", stdout=StringIO())
            self.assertNotIn("SECRET", str(error.exception))
            self.assertLess(len(str(error.exception)), 1000)
            self.assertEqual(before, list(ScheduledJob.objects.order_by("pk").values()))

    def test_many_aliases_have_bounded_deterministic_json_and_text(self):
        from market.live_schedules import MAX_IDENTITY_DETAILS

        for i in range(MAX_IDENTITY_DETAILS + 7):
            ScheduledJob.objects.create(
                name=f"alias {i}",
                task_name="market.ingest_oanda",
                parameters={"instrument": "SECRET" * 5000, "granularity": "H1"},
                interval_seconds=3600,
                next_run_at=self.now,
            )
        first, report = self.report()
        second, _ = self.report()
        self.assertEqual(first, second)
        self.assertEqual(report["schedule_identity_issues"]["omitted"], 7)
        self.assertNotIn("SECRET", first)
        self.assertLess(len(first), 150000)
        messages = []
        for _ in range(2):
            with self.assertRaises(CommandError) as error:
                call_command("seed_canonical", stdout=StringIO())
            messages.append(str(error.exception))
        self.assertEqual(*messages)
        self.assertLess(len(messages[0]), 10000)
        self.assertNotIn("SECRET", messages[0])

    def test_collision_nonzero_seed_deadlines_unchanged_and_latest_catchup(self):
        from operations.services import enqueue_due_jobs

        first = ScheduledJob.objects.get(name="OANDA USD_JPY H1")
        second = ScheduledJob.objects.get(name="OANDA AUD_USD H4")
        first.next_run_at = self.now - timedelta(days=2)
        second.next_run_at = first.next_run_at + timedelta(hours=1)
        first.save()
        second.save()
        before = list(ScheduledJob.objects.order_by("pk").values())
        _, report = self.report()
        self.assertTrue(any("recurring_collision" in e for e in report["integrity_errors"]))
        self.assertEqual(before, list(ScheduledJob.objects.order_by("pk").values()))
        for _ in range(2):
            call_command("seed_canonical", stdout=StringIO())
            self.assertEqual(before, list(ScheduledJob.objects.order_by("pk").values()))
        created = enqueue_due_jobs(self.now)
        self.assertEqual(sum(o.scheduled_job_id == first.pk for o in created), 1)
        self.assertEqual(enqueue_due_jobs(self.now), [])

    def test_seeded_48_schedules_have_no_collisions_or_writes(self):
        before = list(ScheduledJob.objects.order_by("pk").values())
        _, report = self.report(failure=False)
        self.assertEqual(report["integrity_errors"], [])
        self.assertEqual(
            report["schedule_identity_issues"], {"total": 0, "omitted": 0, "details": []}
        )
        self.assertEqual(before, list(ScheduledJob.objects.order_by("pk").values()))
