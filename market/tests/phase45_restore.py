"""Opt-in genuine restore probe, never run against a deployed database.

Restore the exact backup into a new local database named phase45_restore, then:
manage.py shell -c 'from market.tests.phase45_restore import verify; verify()'
No raw row contents or credentials are printed. No evidence is manufactured.
"""

import hashlib
import json
from importlib import import_module
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from market.tests.historical_database import head_fingerprint


def evidence():
    tables = {}
    sequences = {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() "
            "AND tablename<>'django_migrations' ORDER BY tablename"
        )
        names = [row[0] for row in cursor.fetchall()]
        for name in names:
            digest = hashlib.sha256()
            count = 0
            cursor.execute(
                f"SELECT to_jsonb(t)::text FROM {connection.ops.quote_name(name)} t "
                "ORDER BY to_jsonb(t)::text"
            )
            while rows := cursor.fetchmany(1000):
                for (row,) in rows:
                    digest.update(row.encode() + b"\n")
                    count += 1
            tables[name] = {"count": count, "sha256": digest.hexdigest()}
        cursor.execute(
            "SELECT sequencename FROM pg_sequences WHERE schemaname=current_schema() "
            "AND sequencename<>'django_migrations_id_seq' ORDER BY sequencename"
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f"SELECT last_value,is_called FROM {connection.ops.quote_name(name)}")
            sequences[name] = cursor.fetchone()
    return {"tables": tables, "sequences": sequences}


def verify():
    if connection.settings_dict["NAME"] != "phase45_restore" or not connection.settings_dict[
        "HOST"
    ].startswith("/tmp/"):
        raise RuntimeError("Probe requires its named disposable local Unix-socket restore")
    bootstrap = import_module("market.migrations.0027_gate8i_empty_bootstrap")
    original = bootstrap.original
    initial_evidence = evidence()
    with connection.cursor() as cursor:
        initial_recorder = head_fingerprint(cursor)[0]
        cursor.execute("SHOW server_version")
        version = cursor.fetchone()[0]
    MigrationExecutor(connection).migrate(
        [("market", "0026_gate8g_successor_acquisition_activation")]
    )
    if evidence() != initial_evidence:
        raise AssertionError("Prerequisite migration changed restored application evidence")
    with connection.cursor() as cursor:
        before = head_fingerprint(cursor)
    if before[0][: len(initial_recorder)] != initial_recorder:
        raise AssertionError("Prerequisites changed existing recorder identities/timestamps")
    executor = MigrationExecutor(connection)
    executor.loader.replace_migrations = False
    executor.loader.build_graph()
    try:
        executor.migrate([("market", "0027_gate8i_final_dataset_acceptance")])
    except RuntimeError as error:
        refusal = str(error)
    else:
        raise AssertionError("This probe requires the genuine incomplete deployed fixture")
    with connection.cursor() as cursor:
        if head_fingerprint(cursor) != before or evidence() != initial_evidence:
            raise AssertionError("Original refusal changed restored evidence or catalog")
    with patch.object(original, "forward", wraps=original.forward) as delegated:
        try:
            MigrationExecutor(connection).migrate([("market", "0027_gate8i_empty_bootstrap")])
        except RuntimeError as error:
            if str(error) != refusal:
                raise AssertionError("Replacement changed original refusal") from error
        else:
            raise AssertionError("Replacement admitted incomplete deployed history")
        delegated.assert_called_once()
    with connection.cursor() as cursor:
        if head_fingerprint(cursor) != before or evidence() != initial_evidence:
            raise AssertionError("Replacement refusal changed restored evidence or catalog")
    summary = {
        "version": version,
        "genuine_restore": True,
        "accepted_success_proven": False,
        "refusal": refusal,
        "application_tables": len(initial_evidence["tables"]),
        "application_rows": sum(row["count"] for row in initial_evidence["tables"].values()),
        "evidence_sha256": hashlib.sha256(
            json.dumps(initial_evidence, sort_keys=True).encode()
        ).hexdigest(),
        "original_recorder_rows_preserved": len(initial_recorder),
        "delegation_and_atomic_refusal": True,
    }
    print(json.dumps(summary, sort_keys=True))
    return summary
