"""Raw admission probes share the genuine replayable ORB integration fixture."""

import json
from copy import deepcopy
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from market.state.canonical import identity_digest
from market.strategy.persistence import simulation_integrity

OLD = [("market", "0040_strategy_contract_corrections")]
NEW = [("market", "0041_simulation_evidence_admission")]


def insert(record, evidence, *, unavailable=False, extra_net=False):
    intent = record.intent | {
        "cost_sha256": identity_digest(evidence.get("cost")),
        "calendar_sha256": identity_digest(evidence.get("calendar")),
    }
    output = (
        {
            "schema": "phase5/unavailable-v1",
            "strategy": record.evaluation.definition.strategy,
            "reason": "cost_unavailable",
        }
        if unavailable
        else record.output | {"intent_sha256": identity_digest(intent)}
    )
    if extra_net:
        output["net_account"] = "0.000000"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO market_strategysimulation "
            "(evaluation_id,outcome_snapshot_id,intent,outcome_evidence,output,output_sha256,"
            "identity,attempt_key,created_at) VALUES (%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,now()) RETURNING id",
            [
                record.evaluation_id,
                record.outcome_snapshot_id,
                json.dumps(intent),
                json.dumps(evidence),
                json.dumps(output),
                identity_digest(output),
                identity_digest([record.evaluation_id, intent, evidence]),
                record.attempt_key,
            ],
        )
        return cursor.fetchone()[0]


def probe_evidence(test, record):
    evidence = record.outcome_evidence
    nulls = evidence | {"cost": None, "calendar": None, "terms": None}
    # Reproduce the review finding at exact 0040: hashes agree, replay does not.
    with transaction.atomic():
        pk = insert(record, nulls)
        test.assertEqual(
            simulation_integrity()["violations"],
            [{"id": pk, "reason": "simulation_integrity_failure"}],
        )
        MigrationExecutor(connection).migrate(NEW)
        test.assertEqual(
            simulation_integrity()["violations"],
            [{"id": pk, "reason": "simulation_integrity_failure"}],
        )
        transaction.set_rollback(True)
    # The new migration changes admission only; populated evidence is untouched
    # through forward/reverse/reapply, including a genuine available record.
    with transaction.atomic():
        pk = insert(record, evidence)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_jsonb(t) FROM market_strategysimulation t WHERE id=%s", [pk])
            before = cursor.fetchone()[0]
        for target in (NEW, OLD, NEW):
            MigrationExecutor(connection).migrate(target)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT to_jsonb(t) FROM market_strategysimulation t WHERE id=%s", [pk]
                )
                test.assertEqual(cursor.fetchone()[0], before)
            test.assertEqual(simulation_integrity()["violations"], [])
        transaction.set_rollback(True)
    MigrationExecutor(connection).migrate(NEW)
    role = "p5_evidence_" + uuid4().hex
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOLOGIN')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            cursor.execute(f'GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA public TO "{role}"')
            cursor.execute(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            cursor.execute(f'SET LOCAL ROLE "{role}"')
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            test.assertFalse(cursor.fetchone()[0])
        invalid = []
        for kind in ("cost", "calendar", "terms"):
            invalid.append({k: v for k, v in evidence.items() if k != kind})
            invalid.extend(evidence | {kind: v} for v in (None, [], "bad", True, 3))
            invalid.append(evidence | {kind: evidence[kind] | {"extra": 1}})
            for key in evidence[kind]:
                invalid.append(
                    evidence | {kind: {k: v for k, v in evidence[kind].items() if k != key}}
                )
                wrong = (
                    (None, True, {}) if isinstance(evidence[kind][key], list) else (None, True, [])
                )
                invalid.extend(evidence | {kind: evidence[kind] | {key: v}} for v in wrong)
        terms = evidence["terms"]
        for key, values in {
            "base_currency": ("", "usd", " USD", "XYZ", "USD"),
            "quote_currency": ("", "usd"),
            "account_currency": ("", "cad"),
            "source_sha256": ("a", "A" * 64, "z" * 64),
            "provenance": ("", "\u00a0"),
            "cost_unit": ("pips",),
            "conversion_unit": ("quote_per_account",),
            "conversion_rate": ("NaN", "Infinity", "1e2", "0", "-1", 1),
            "known_at": ("2026-01-05T08:00:00", "2027-01-01T00:00:00.000000+00:00"),
            "from_at": (terms["through_at"].replace("09:", "10:"),),
            "through_at": ("2025-01-01T00:00:00.000000+00:00",),
            "conversion_at": ("2026-02-30T00:00:00.000000+00:00",),
            "rollovers": (
                [[terms["from_at"], "NaN"]],
                [[terms["from_at"]]],
                [["2025-01-01T00:00:00.000000+00:00", "0"]],
            ),
        }.items():
            invalid.extend(evidence | {"terms": terms | {key: value}} for value in values)
        invalid.extend(
            [
                evidence | {"cost": evidence["cost"] | {"spread": "-0.1"}},
                evidence | {"cost": evidence["cost"] | {"latency_seconds": "0"}},
                evidence
                | {
                    "calendar": evidence["calendar"]
                    | {"open_intervals": [[terms["from_at"], terms["from_at"]]]}
                },
            ]
        )
        for candidate in invalid:
            with (
                test.subTest(evidence=candidate),
                test.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                insert(record, candidate)
        for candidate, unavailable in ((deepcopy(evidence), False), (nulls, True)):
            with transaction.atomic():
                insert(record, candidate, unavailable=unavailable)
                test.assertEqual(simulation_integrity()["violations"], [])
                transaction.set_rollback(True)
        with test.assertRaises(DatabaseError), transaction.atomic():
            insert(record, nulls, unavailable=True, extra_net=True)
        transaction.set_rollback(True)
