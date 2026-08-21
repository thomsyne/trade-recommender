import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host]
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]
if PUBLIC_URL:
    CSRF_TRUSTED_ORIGINS.append(PUBLIC_URL)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "market",
    "forecasts",
    "research",
    "operations",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "dashboard.middleware.TrustedPortalNullOriginMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "dashboard.context_processors.market_navigation",
                "dashboard.context_processors.static_asset_version",
            ],
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "trade_recommender"),
        "USER": os.getenv("POSTGRES_USER", "trade_recommender"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "local-dev-only"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-ca"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "today"
LOGOUT_REDIRECT_URL = "login"
LOGIN_THROTTLE_FAILURES = int(os.getenv("LOGIN_THROTTLE_FAILURES", "5"))
LOGIN_THROTTLE_MINUTES = int(os.getenv("LOGIN_THROTTLE_MINUTES", "15"))
READINESS_MIN_FREE_GB = float(os.getenv("READINESS_MIN_FREE_GB", "2"))
READINESS_BACKUP_MAX_AGE_HOURS = int(os.getenv("READINESS_BACKUP_MAX_AGE_HOURS", "8"))
READINESS_BACKUP_MARKER = os.getenv("READINESS_BACKUP_MARKER", "")
READINESS_DISK_PATH = os.getenv("READINESS_DISK_PATH", str(BASE_DIR))

OANDA_ENVIRONMENT = os.getenv("OANDA_ENVIRONMENT", "practice")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")
OANDA_TOKEN = os.getenv("OANDA_TOKEN") or os.getenv("OANDA_API_KEY_TEST", "")
EODHD_API_TOKEN = os.getenv("EODHD_API_TOKEN") or os.getenv("EODHD_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RECOMMENDATION_PROVIDER = os.getenv("RECOMMENDATION_PROVIDER", "anthropic")
RECOMMENDATION_MODEL = os.getenv("RECOMMENDATION_MODEL", "claude-sonnet-5")
RECOMMENDATION_SCHEDULE_ENABLED = os.getenv("RECOMMENDATION_SCHEDULE_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
RECOMMENDATION_METHOD_VERSION = int(os.getenv("RECOMMENDATION_METHOD_VERSION", "1"))
RECOMMENDATION_MAX_OUTPUT_TOKENS = int(os.getenv("RECOMMENDATION_MAX_OUTPUT_TOKENS", "6000"))
RECOMMENDATION_INPUT_USD_PER_MTOK = Decimal(os.getenv("RECOMMENDATION_INPUT_USD_PER_MTOK", "2"))
RECOMMENDATION_OUTPUT_USD_PER_MTOK = Decimal(os.getenv("RECOMMENDATION_OUTPUT_USD_PER_MTOK", "10"))
RECOMMENDATION_MAX_RUN_COST_USD = Decimal(os.getenv("RECOMMENDATION_MAX_RUN_COST_USD", "0.10"))
RECOMMENDATION_DAILY_BUDGET_USD = Decimal(os.getenv("RECOMMENDATION_DAILY_BUDGET_USD", "2"))
RECOMMENDATION_MONTHLY_BUDGET_USD = Decimal(os.getenv("RECOMMENDATION_MONTHLY_BUDGET_USD", "40"))

POSTMORTEM_INTERPRETATION_ENABLED = os.getenv(
    "POSTMORTEM_INTERPRETATION_ENABLED", "false"
).lower() in {"1", "true", "yes"}
POSTMORTEM_MODEL = os.getenv("POSTMORTEM_MODEL", "claude-sonnet-5")
POSTMORTEM_METHOD_VERSION = int(os.getenv("POSTMORTEM_METHOD_VERSION", "1"))
POSTMORTEM_MAX_OUTPUT_TOKENS = int(os.getenv("POSTMORTEM_MAX_OUTPUT_TOKENS", "1800"))
POSTMORTEM_INPUT_USD_PER_MTOK = Decimal(os.getenv("POSTMORTEM_INPUT_USD_PER_MTOK", "2"))
POSTMORTEM_OUTPUT_USD_PER_MTOK = Decimal(os.getenv("POSTMORTEM_OUTPUT_USD_PER_MTOK", "10"))
POSTMORTEM_PRICING_VERSION = os.getenv(
    "POSTMORTEM_PRICING_VERSION", "anthropic-standard-2026-08-10"
)
POSTMORTEM_MAX_RUN_COST_USD = Decimal(os.getenv("POSTMORTEM_MAX_RUN_COST_USD", "0.10"))
POSTMORTEM_DAILY_BUDGET_USD = Decimal(os.getenv("POSTMORTEM_DAILY_BUDGET_USD", "2"))
POSTMORTEM_MONTHLY_BUDGET_USD = Decimal(os.getenv("POSTMORTEM_MONTHLY_BUDGET_USD", "20"))

EMAIL_DELIVERY_ENABLED = os.getenv("EMAIL_DELIVERY_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "465"))
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "true").lower() in {"1", "true", "yes"}
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "false").lower() in {"1", "true", "yes"}
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER") or os.getenv("EMAIL_AUTH_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD") or os.getenv("EMAIL_AUTH_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")

if EMAIL_DELIVERY_ENABLED and not all(
    (PUBLIC_URL, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL, OWNER_EMAIL)
):
    raise RuntimeError(
        "Email delivery requires PUBLIC_URL, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, "
        "DEFAULT_FROM_EMAIL, and OWNER_EMAIL"
    )
