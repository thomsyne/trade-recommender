from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from operations.models import ScheduledJob


@override_settings(DEBUG=True)
class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.user = get_user_model().objects.get(username="owner")
        cls.user.set_password("orb-demo-only")
        cls.user.save(update_fields=("password",))

    def test_private_pages_redirect_anonymous_users(self):
        response = self.client.get(reverse("today"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_today_shows_four_pairs_and_fixture_warning_without_fake_forecasts(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("today"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fixture mode")
        self.assertContains(response, "No forecast issued", count=4)
        for pair in ("USD/CAD", "GBP/USD", "EUR/GBP", "EUR/USD"):
            self.assertContains(response, pair)

    def test_pair_workspace_and_operations_are_rendered(self):
        self.client.force_login(self.user)

        pair = self.client.get(reverse("market-detail", args=("USD_CAD",)))
        operations = self.client.get(reverse("operations"))

        self.assertContains(pair, "DECISION ENGINE LOCKED", html=False)
        self.assertContains(pair, "chart-data")
        self.assertContains(operations, "Rights-aware registry")
        self.assertContains(operations, "WAITING FOR TOKEN")

    def test_health_checks_real_database_connection_without_authentication(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": True})

    def test_repeated_seed_does_not_postpone_existing_schedule(self):
        job = ScheduledJob.objects.first()
        expected = timezone.now() - timedelta(minutes=5)
        ScheduledJob.objects.filter(pk=job.pk).update(next_run_at=expected)

        call_command("seed_demo", verbosity=0)

        job.refresh_from_db()
        self.assertEqual(job.next_run_at, expected)

    @override_settings(
        PUBLIC_URL="https://portal.example",
        CSRF_TRUSTED_ORIGINS=["https://portal.example"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
    def test_owner_can_log_in_through_trusted_https_proxy(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        login = csrf_client.get(reverse("login"), secure=True)
        token = login.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("login"),
            {"username": "owner", "password": "orb-demo-only", "csrfmiddlewaretoken": token},
            HTTP_ORIGIN="https://portal.example",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertRedirects(response, reverse("today"))

    @override_settings(
        PUBLIC_URL="https://portal.example",
        CSRF_TRUSTED_ORIGINS=["https://portal.example"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
    def test_owner_can_log_in_from_matching_opaque_portal_context(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        login = csrf_client.get(reverse("login"), secure=True, HTTP_HOST="portal.example")
        token = login.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("login"),
            {"username": "owner", "password": "orb-demo-only", "csrfmiddlewaretoken": token},
            HTTP_HOST="portal.example",
            HTTP_ORIGIN="null",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertRedirects(response, reverse("today"))

    @override_settings(
        PUBLIC_URL="https://portal.example",
        CSRF_TRUSTED_ORIGINS=["https://portal.example"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
    def test_opaque_origin_on_wrong_host_remains_forbidden(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        login = csrf_client.get(reverse("login"), secure=True, HTTP_HOST="wrong.example")
        token = login.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("login"),
            {"username": "owner", "password": "orb-demo-only", "csrfmiddlewaretoken": token},
            HTTP_HOST="wrong.example",
            HTTP_ORIGIN="null",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(
        PUBLIC_URL="https://portal.example",
        CSRF_TRUSTED_ORIGINS=["https://portal.example"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
    def test_opaque_portal_origin_without_csrf_token_remains_forbidden(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)

        response = csrf_client.post(
            reverse("login"),
            {"username": "owner", "password": "orb-demo-only"},
            HTTP_HOST="portal.example",
            HTTP_ORIGIN="null",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 403)
