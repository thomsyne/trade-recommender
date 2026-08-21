import os
from urllib.parse import urlsplit

from config.settings import *  # noqa: F403


def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required in production")
    return value


DEBUG = False
SECRET_KEY = required("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or SECRET_KEY == "local-development-only":
    raise RuntimeError("DJANGO_SECRET_KEY must be a unique value of at least 50 characters")

PUBLIC_URL = required("PUBLIC_URL").rstrip("/")
public = urlsplit(PUBLIC_URL)
if public.scheme != "https" or not public.hostname or public.path:
    raise RuntimeError("PUBLIC_URL must be an HTTPS origin without a path")

ALLOWED_HOSTS = [public.hostname]
CSRF_TRUSTED_ORIGINS = [PUBLIC_URL]

database_password = required("POSTGRES_PASSWORD")
if database_password == "local-dev-only":
    raise RuntimeError("POSTGRES_PASSWORD must not use the development value")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_AGE = 43_200
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
X_FRAME_OPTIONS = "DENY"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 14},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
