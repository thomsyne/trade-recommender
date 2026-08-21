import getpass
import secrets

import pyotp
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dashboard.models import OwnerMFA


class Command(BaseCommand):
    help = "Create/update the single owner and enroll Google Authenticator-compatible MFA"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="owner")
        parser.add_argument("--email", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        password = getpass.getpass("New owner password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise CommandError("Passwords do not match")
        validate_password(password)
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=options["username"], issuer_name="FX Forecast Lab"
        )
        self.stdout.write("Add this URI to Google Authenticator or another TOTP application:")
        self.stdout.write(uri)
        token = input("Current six-digit code: ").strip()
        if not pyotp.TOTP(secret).verify(token, valid_window=1):
            raise CommandError("The authentication code was not valid; no changes were saved")
        recovery_codes = [secrets.token_hex(5) for _ in range(10)]
        user, _ = get_user_model().objects.get_or_create(username=options["username"])
        user.email = options["email"]
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()
        OwnerMFA.objects.update_or_create(
            user=user,
            defaults={
                "secret": secret,
                "recovery_code_hashes": [make_password(code) for code in recovery_codes],
                "confirmed_at": timezone.now(),
            },
        )
        self.stdout.write(
            self.style.SUCCESS("Owner MFA configured. Store these one-use codes offline:")
        )
        self.stdout.write("\n".join(recovery_codes))
