"""Isolated test settings for detector-v2 ORM query-budget verification.

The production migration graph intentionally contains data-gated activation
migrations.  Query-budget tests need model-shaped PostgreSQL tables, not the
accepted persistent research dataset, so this settings module asks Django to
create those tables directly from the current models in its disposable test
database.
"""

from config.settings import *  # noqa: F403

MIGRATION_MODULES = {
    "admin": None,
    "auth": None,
    "contenttypes": None,
    "dashboard": None,
    "forecasts": None,
    "market": None,
    "operations": None,
    "research": None,
    "sessions": None,
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
