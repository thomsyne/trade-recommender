"""Hash-consistent SQL probes and Python parity, including non-superuser admission."""

import json
from importlib import import_module
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from market.models import StrategyEvaluation
from market.state.canonical import identity_digest
from market.strategy.contracts import Unavailable, encoded
from market.strategy.persistence import calculate
from market.strategy.schema import COMPONENT, FIELDS, validate_part
from market.tests import test_strategy_library_simulation as fixtures
from market.tests.test_strategy_library_persistence import snapshot


class ClosedSchemaTests(TestCase):
    def test_non_superuser_rejects_hash_consistent_cross_kind_and_missingness(self):
        source = snapshot()
        row, _ = calculate(source.pk, "fixed-risk-v1")
        role = "p5_contract_" + uuid4().hex
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOLOGIN')
            cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            cursor.execute(
                f'GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON ALL TABLES IN SCHEMA public TO "{role}"'
            )
            cursor.execute(f'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            cursor.execute(f'SET LOCAL ROLE "{role}"')
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            self.assertFalse(cursor.fetchone()[0])
        original = row.output["outputs"][0]
        invalid = [
            original | {"value": "20.000000"},
            original | {"multiplier": True},
            original | {"multiplier": "NaN"},
            original | {"multiplier": "1e0"},
            original | {"multiplier": 1},
            original | {"evidence": [False]},
            {k: v for k, v in original.items() if k != "reason"},
            json.loads(encoded(Unavailable("fixed-risk-v1", "unknown"))) | {"buffered": "0.000000"},
        ]
        for i, part in enumerate(invalid):
            with self.subTest(part=part):
                evidence = row.evidence | {"probe": i}
                output = row.output | {"outputs": [part]}
                with self.assertRaises(DatabaseError), transaction.atomic():
                    StrategyEvaluation.objects.create(
                        definition=row.definition,
                        snapshot=source,
                        evidence=evidence,
                        evidence_sha256=identity_digest(evidence),
                        output=output,
                        output_sha256=identity_digest(output),
                        identity=identity_digest(
                            [row.definition.body_sha256, source.pk, identity_digest(evidence)]
                        ),
                    )
        for sql in (
            "UPDATE market_strategyevaluation SET previous_id=id WHERE id=%s",
            "DELETE FROM market_strategyevaluation WHERE id=%s",
        ):
            with (
                self.assertRaises(DatabaseError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, [row.pk])
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE market_strategyevaluation CASCADE")

    def test_closed_shape_python_sql_parity_for_every_field(self):
        frozen = import_module("market.migrations.0040_strategy_contract_corrections")
        self.assertEqual(FIELDS, frozen.FIELDS)
        self.assertEqual(COMPONENT, frozen.COMPONENT)
        f = fixtures.SimulationTests()
        f.setUp()
        samples = {
            "setup": json.loads(encoded(f.setup)),
            "execution": json.loads(encoded(f.run_model())),
            "unavailable": json.loads(encoded(Unavailable("fixture", "missing"))),
        }
        source = snapshot()
        for strategy, kind in (("ewmac-d-v1", "continuous"), ("fixed-risk-v1", "risk")):
            samples[kind] = calculate(source.pk, strategy)[0].output["outputs"][0]
        from market.strategy.contracts import ExecutionIntent

        samples["intent"] = json.loads(encoded(ExecutionIntent(*(["a" * 64] * 4))))
        for kind, sample in samples.items():
            variants = [sample, sample | {"extra": "cross_kind"}]
            for key in sample:
                variants.extend(
                    (
                        {k: v for k, v in sample.items() if k != key},
                        sample | {key: True},
                        sample | {key: None},
                    )
                )
            if kind == "setup":
                variants.extend(
                    sample | {"entry_at": t}
                    for t in (
                        "2026-01-01",
                        "2026-01-01T12:00:00",
                        "2026-02-30T12:00:00.000000+00:00",
                    )
                )
            if kind == "execution":
                variants.extend(
                    (sample | {"intent_sha256": "x"}, sample | {"net_account": "Infinity"})
                )
            if "reason" in sample:
                variants.extend(
                    sample | {"reason": value}
                    for value in ("\u00a0", "\u2000\u2028", "\v\f", "\u200b")
                )
            for value in variants:
                with self.subTest(kind=kind, value=value):
                    try:
                        validate_part(value, kind)
                        expected = True
                    except (ValueError, TypeError):
                        expected = False
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT phase5_v2_part(%s::jsonb,%s)", [json.dumps(value), kind]
                        )
                        self.assertEqual(cursor.fetchone()[0], expected)
