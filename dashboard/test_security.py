import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pyotp
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dashboard.models import LoginThrottle, OwnerMFA


class ProductionHostnameSettingsTests(SimpleTestCase):
    def test_public_url_is_the_single_source_for_hosts_and_csrf(self):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings_production",
                "DJANGO_SECRET_KEY": "test-only-" + "x" * 50,
                "POSTGRES_PASSWORD": "test-only-database-password",
                "PUBLIC_URL": "https://fx-forecast.thomsyne.dev",
            }
        )
        environment.pop("DJANGO_ALLOWED_HOSTS", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; from django.conf import settings; "
                    "print(json.dumps([settings.PUBLIC_URL, settings.ALLOWED_HOSTS, "
                    "settings.CSRF_TRUSTED_ORIGINS]))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(
            json.loads(result.stdout),
            [
                "https://fx-forecast.thomsyne.dev",
                ["fx-forecast.thomsyne.dev"],
                ["https://fx-forecast.thomsyne.dev"],
            ],
        )


@override_settings(
    DEBUG=False,
    LOGIN_THROTTLE_FAILURES=3,
    LOGIN_THROTTLE_MINUTES=15,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ProductionAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="owner", password="a-strong-test-password"
        )
        cls.secret = pyotp.random_base32()
        cls.recovery = "abcd1234ef"
        OwnerMFA.objects.create(
            user=cls.user,
            secret=cls.secret,
            recovery_code_hashes=[make_password(cls.recovery)],
            confirmed_at=timezone.now(),
        )

    def login(self, token, password="a-strong-test-password"):
        return self.client.post(
            reverse("login"),
            {"username": "owner", "password": password, "otp_token": token},
        )

    def test_totp_is_required_and_valid_token_authenticates(self):
        self.assertEqual(self.login("").status_code, 200)
        response = self.login(pyotp.TOTP(self.secret).now())
        self.assertRedirects(response, reverse("today"), fetch_redirect_response=False)

    def test_admin_login_cannot_bypass_owner_mfa(self):
        response = self.client.get(reverse("admin:login"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('admin:login')}",
            fetch_redirect_response=False,
        )

    def test_recovery_code_is_one_use(self):
        self.assertRedirects(
            self.login(self.recovery), reverse("today"), fetch_redirect_response=False
        )
        self.client.logout()
        self.assertEqual(self.login(self.recovery).status_code, 200)

    def test_repeated_failures_are_throttled_without_storing_identifiers(self):
        for _ in range(3):
            self.login("000000", password="wrong-password")
        throttle = LoginThrottle.objects.get()
        self.assertEqual(len(throttle.key), 64)
        self.assertGreater(throttle.locked_until, timezone.now())
        self.assertEqual(self.login(pyotp.TOTP(self.secret).now()).status_code, 200)


class ReadinessTests(TestCase):
    def test_readiness_checks_database_migrations_disk_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "last-backup"
            marker.touch()
            with override_settings(
                READINESS_DISK_PATH=directory,
                READINESS_MIN_FREE_GB=0,
                READINESS_BACKUP_MARKER=str(marker),
            ):
                response = self.client.get(reverse("ready"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "checks": []})

    @override_settings(READINESS_BACKUP_MARKER="/definitely/missing/backup-marker")
    def test_readiness_fails_when_backup_is_missing(self):
        response = self.client.get(reverse("ready"))
        self.assertEqual(response.status_code, 503)
        self.assertIn("backup", response.json()["checks"])
