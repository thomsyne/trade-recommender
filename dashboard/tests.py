import re
from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from forecasts.services import issue_all_baselines
from operations.models import ScheduledJob
from research.models import (
    DocumentRepresentation,
    RawRetrieval,
    ResearchDocument,
    SourcePolicy,
)


@override_settings(DEBUG=True, OANDA_TOKEN="")
class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        issue_all_baselines(allow_fixture=True)
        cls.user = get_user_model().objects.get(username="owner")
        cls.user.set_password("orb-demo-only")
        cls.user.save(update_fields=("password",))

    def test_private_pages_redirect_anonymous_users(self):
        response = self.client.get(reverse("today"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_today_shows_four_pairs_and_locked_fixture_baselines(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("today"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fixture mode")
        self.assertContains(response, "No trade", count=4)
        self.assertContains(response, "Mechanical EWMA control", count=4)
        for pair in ("USD/CAD", "GBP/USD", "EUR/GBP", "EUR/USD"):
            self.assertContains(response, pair)

    def test_static_assets_have_content_based_cache_versions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("today"))
        content = response.content.decode()

        css_version = re.search(r"app\.css\?v=([a-f0-9]{12})", content)
        js_version = re.search(r"app\.js\?v=([a-f0-9]{12})", content)
        self.assertIsNotNone(css_version)
        self.assertIsNotNone(js_version)
        self.assertEqual(css_version.group(1), js_version.group(1))

    def test_pair_workspace_and_operations_are_rendered(self):
        self.client.force_login(self.user)

        pair = self.client.get(reverse("market-detail", args=("USD_CAD",)))
        operations = self.client.get(reverse("operations"))
        calibration = self.client.get(reverse("calibration"))
        paper = self.client.get(reverse("paper-trades"))
        exposure = self.client.get(reverse("exposure"))

        self.assertContains(pair, "LOCKED MECHANICAL CONTROL", html=False)
        self.assertContains(pair, "GOVERNED RECOMMENDATION", html=False)
        self.assertContains(pair, "Awaiting the first model assessment")
        self.assertContains(pair, "IMMUTABLE TIMELINE", html=False)
        self.assertContains(pair, "chart-data")
        self.assertContains(pair, f'href="{reverse("research")}"')
        self.assertNotContains(pair, "next slice")
        self.assertContains(operations, "Rights-aware registry")
        self.assertContains(operations, "WAITING FOR CREDENTIAL")
        self.assertContains(operations, "Prospective OANDA cost snapshots")
        self.assertContains(operations, "No account-specific terms captured yet")
        self.assertContains(calibration, "Insufficient sample—do not infer skill")
        self.assertContains(calibration, "No v2 recommendation has reached five later")
        self.assertContains(paper, "Insufficient sample—do not infer profitability")
        self.assertContains(paper, "No directional v2 recommendation exists yet")
        self.assertContains(paper, "Stress uncertainty instead of fabricating precision")
        self.assertContains(paper, "3% adverse annual financing")
        self.assertContains(paper, "Costs are pip sensitivities, not exact charges")
        self.assertContains(exposure, "Currency exposure")
        self.assertContains(exposure, "No unresolved directional v2 setup exists")
        self.assertContains(exposure, "No position size")

    def test_research_surface_is_private_read_only_and_escapes_source_text(self):
        self.assertRedirects(
            self.client.get(reverse("research")), f"{reverse('login')}?next=/research/"
        )
        policy = SourcePolicy.objects.get(slug="bank-of-canada")
        retrieval = RawRetrieval.objects.create(
            source_policy=policy,
            url="https://www.bankofcanada.ca/content_type/press-releases/feed/",
            request_fingerprint="a" * 64,
            fetched_at=datetime(2026, 8, 19, tzinfo=UTC),
            http_status=200,
            content_type="application/rss+xml",
            byte_count=4,
            body_sha256="b" * 64,
            body=b"test",
            retention_decision="official-public-record",
        )
        document = ResearchDocument.objects.create(
            canonical_url="https://www.bankofcanada.ca/2026/08/test/",
            canonical_hash="c" * 64,
            title="<script>alert('source')</script>",
            published_at=datetime(2026, 8, 18, tzinfo=UTC),
            first_observed_at=datetime(2026, 8, 19, tzinfo=UTC),
            quality=ResearchDocument.Quality.VERIFIED,
        )
        DocumentRepresentation.objects.create(
            document=document,
            retrieval=retrieval,
            source_item_id="test",
            dedup_key="d" * 64,
            source_title=document.title,
            source_published_at=document.published_at,
            summary="<img src=x onerror=alert(1)>",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("research"))
        content = response.content.decode()
        self.assertContains(response, "Evidence only")
        self.assertContains(response, "Four-economy coverage")
        self.assertContains(response, "0/8 COLLECTED")
        self.assertContains(response, "No consensus is inferred")
        self.assertContains(response, "Official statistical agencies")
        self.assertContains(response, "Trading Economics")
        self.assertContains(response, "Consensus remains optional and separate")
        self.assertNotIn("<script>alert", content)
        self.assertNotIn("<img src=x", content)
        self.assertIn("&lt;script&gt;", content)

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
