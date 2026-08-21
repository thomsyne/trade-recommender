import hashlib
from datetime import timedelta
from functools import wraps

import pyotp
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.hashers import check_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.utils import timezone

from dashboard.models import LoginThrottle, OwnerMFA

INVALID_LOGIN = "The credentials or authentication code were not accepted."


class OwnerAuthenticationForm(AuthenticationForm):
    otp_token = forms.CharField(label="Authentication or recovery code", strip=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["otp_token"].required = not settings.DEBUG

    def clean(self):
        key = _throttle_key(self.request, self.data.get("username", ""))
        if _is_locked(key):
            raise ValidationError(INVALID_LOGIN, code="invalid_login")
        try:
            cleaned = super().clean()
            user = self.get_user()
            if not user.is_superuser or (
                not settings.DEBUG and not _verify_mfa(user, cleaned.get("otp_token", ""))
            ):
                raise ValidationError(INVALID_LOGIN, code="invalid_login")
        except ValidationError:
            _record_failure(key)
            raise ValidationError(INVALID_LOGIN, code="invalid_login") from None
        LoginThrottle.objects.filter(key=key).delete()
        return cleaned


class OwnerLoginView(LoginView):
    authentication_form = OwnerAuthenticationForm
    redirect_authenticated_user = True


def _throttle_key(request, username):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",", 1)[0].strip()
    address = forwarded or request.META.get("REMOTE_ADDR", "unknown")
    return hashlib.sha256(f"{username.strip().lower()}|{address}".encode()).hexdigest()


def _is_locked(key):
    row = LoginThrottle.objects.filter(key=key).first()
    return bool(row and row.locked_until and row.locked_until > timezone.now())


@transaction.atomic
def _record_failure(key):
    row, _ = LoginThrottle.objects.select_for_update().get_or_create(key=key)
    row.failures += 1
    if row.failures >= settings.LOGIN_THROTTLE_FAILURES:
        row.locked_until = timezone.now() + timedelta(minutes=settings.LOGIN_THROTTLE_MINUTES)
    row.save()


@transaction.atomic
def _verify_mfa(user, token):
    try:
        device = OwnerMFA.objects.select_for_update().get(user=user)
    except OwnerMFA.DoesNotExist:
        return False
    normalized = token.replace(" ", "").replace("-", "")
    if normalized.isdigit() and pyotp.TOTP(device.secret).verify(normalized, valid_window=1):
        return True
    for index, encoded in enumerate(device.recovery_code_hashes):
        if check_password(normalized.lower(), encoded):
            hashes = list(device.recovery_code_hashes)
            hashes.pop(index)
            device.recovery_code_hashes = hashes
            device.save(update_fields=("recovery_code_hashes",))
            return True
    return False


def owner_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden("Owner access required")
        return view(request, *args, **kwargs)

    return wrapped
