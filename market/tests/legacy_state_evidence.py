"""Synthetic pre-0036 evidence for the original historical descriptor tests.

Only fixture insertion omits the new recording trigger. All lineage, content,
append-only and snapshot guards remain installed. This helper must never be
used by tests of new evidence or ingestion/snapshot concurrency.
"""

from contextlib import contextmanager
from unittest.mock import patch

from django.db import connection, transaction

from market import services


@contextmanager
def legacy_evidence():
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        role = cursor.fetchone()[0]
        cursor.execute("RESET ROLE")
        cursor.execute(
            "ALTER TABLE market_candleobservation DISABLE TRIGGER market_candleobservation_a_recording"
        )
        cursor.execute(f"SET LOCAL ROLE {connection.ops.quote_name(role)}")
        try:
            yield
        finally:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("RESET ROLE")
            cursor.execute(
                "ALTER TABLE market_candleobservation ENABLE TRIGGER market_candleobservation_a_recording"
            )
            cursor.execute(f"SET LOCAL ROLE {connection.ops.quote_name(role)}")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def store_ingestion(*args, **kwargs):
    with legacy_evidence():
        return services.store_ingestion(*args, **kwargs)


def ingest(*args, **kwargs):
    from market.tests import test_live_observations

    with patch.object(test_live_observations, "store_ingestion", store_ingestion):
        return test_live_observations.ingest(*args, **kwargs)
