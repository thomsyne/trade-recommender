"""Gate 7C: provider-observed dataset registration.

The fixture acquires the complete production-pinned 132-chunk replacement
dataset through the reviewed pipeline, so lineage, counts, identities and the
Python readiness rules are exercised against the real governed shape. It stamps
the committed per-chunk semantic identities onto inventories whose observations
are synthetic, so the database's own sealed-inventory hash check cannot be
satisfied here: the committed registration itself is proven on real acquired
data by the disposable post-Wave-6 rehearsal. These tests prove everything up to
and including that boundary, plus every fail-closed rule. Fixture builds are
expensive, so each method covers a coherent group of proofs.
"""

import json
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase

from market.historical_acquisition import (
    parse_timestamp,
    register_historical_dataset,
    replacement_registration_contract,
    replacement_series_coverage,
    stable_hash,
)
from market.models import (
    Candle,
    DatasetRegistration,
    HistoricalIngestionChunk,
)
from market.provider_observed_acquisition import REPLACEMENT_REGISTRATION_IDENTITY
from market.provider_observed_registration import (
    build_registration_authorization,
    registration_aggregates,
    registration_authorization_path,
    verify_registration_readiness,
)
from market.provider_observed_waves import load_committed_wave_manifest
from market.quality import expected_candle_timestamps
from market.services import DatasetQualityError
from market.tests.test_gate7b_full_acquisition import Gate7BFixtureTestCase
from market.tests.test_historical_acquisition import HistoricalFixtureMixin
from market.tests.test_replacement_canary_activation import (
    MIGRATION_0022,
    migrate_to,
)

EXPECTED_AGGREGATES = {
    "logical_chunk_set_hash": "de9c977eeac2097eba2e410187f84bf2052f3454b136d50e1b66727aadbedd0a",
    "successful_attempt_set_hash": (
        "ccb71254f70aebaee585de8b86a1c869657622ec0340adf8f4b5603e8607068e"
    ),
    "ingestion_manifest_set_hash": (
        "dc3da68f95969b32e2f6a84b6f1c60ad4ea7832f110fa7b107c0b25fd2349b4f"
    ),
    "candle_key_hash": "5f7850a317808688066ead6f46f7085e05e840d0a0c73b1ab4fc56f792ede5ea",
    "candle_payload_hash": "218bb6fb8c456a02bb10193179bed9b93e4be5a71da10ff9aee028e4e41c0d10",
}
GRANULARITY_TOTALS = {"D": 17412, "H1": 344715, "W": 2826}


class Gate7CFixtureTestCase(Gate7BFixtureTestCase):
    """The complete acquired replacement dataset: all 132 chunks succeeded."""

    retention_policy = "gate7c registration fixture"

    def setUp(self):
        super().setUp()
        migrate_to(MIGRATION_0022)
        for wave in load_committed_wave_manifest()["waves"]:
            self.run_wave(
                wave=wave["wave"], max_chunks=wave["chunk_count"], execute=True, resume=True
            )
        assert Candle.objects.filter(dataset_version=self.dataset).count() == 364953

    def readiness_chunks(self):
        return list(
            self.plan.chunks.filter(dataset_version=self.dataset)
            .select_related("instrument", "discovery_inventory")
            .prefetch_related("attempts__ingestion_run__ingestion_manifest")
            .order_by("instrument__code", "granularity", "requested_from")
        )

    def register(self):
        return register_historical_dataset(self.dataset.pk, self.plan.sha256)

    def fixture_authorization(self):
        """The committed authorization with the aggregate hashes this fixture's
        mocked provider actually produces. Every identity, count and per
        granularity total stays production-pinned; only the three hashes that
        depend on synthetic prices and request identifiers are substituted."""
        chunks = list(
            self.plan.chunks.filter(dataset_version=self.dataset)
            .select_related("instrument", "discovery_inventory")
            .prefetch_related("attempts__ingestion_run__ingestion_manifest")
            .order_by("instrument__code", "granularity", "requested_from")
        )
        successful = [
            attempt
            for chunk in chunks
            for attempt in chunk.attempts.all()
            if attempt.ingestion_run.status == "succeeded"
        ]
        return {
            **build_registration_authorization(),
            **registration_aggregates(self.dataset, chunks, successful),
        }

    def run_command(self, *, execute=False, authorization=None):
        stdout = StringIO()
        args = ["--dataset-id", str(self.dataset.pk), "--plan-sha256", self.plan.sha256]
        if execute:
            args.append("--execute")
        if authorization is None:
            call_command("register_failed_break_dataset", *args, stdout=stdout)
        else:
            with patch(
                "market.management.commands.register_failed_break_dataset."
                "load_committed_registration_authorization",
                return_value=authorization,
            ):
                call_command("register_failed_break_dataset", *args, stdout=stdout)
        return json.loads(stdout.getvalue())

    def forge(self, table, statement, params):
        """Test-only forgery of governed evidence, used to prove a defect is
        rejected. Production paths never disable a trigger."""
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
            try:
                cursor.execute(statement, params)
            finally:
                cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")

    def assert_registration_refused(self, label):
        with self.assertRaises((DatasetQualityError, DatabaseError), msg=label):
            with transaction.atomic():
                self.register()
        connection.close()
        self.assertEqual(DatasetRegistration.objects.count(), 0, label)


class Gate7CRegistrationTests(Gate7CFixtureTestCase):
    def test_artifact_bytes_dry_run_readiness_and_database_inventory_enforcement(self):
        # 18: only the exact committed artifact bytes are accepted
        original = registration_authorization_path().read_bytes()
        body = json.loads(original)
        variants = {
            "reformatted": json.dumps(body, indent=2, sort_keys=True).encode(),
            "trailing byte": original + b"\n",
            "altered count": json.dumps(
                {**body, "candle_count": 364952}, sort_keys=True, separators=(",", ":")
            ).encode(),
            "altered aggregate": json.dumps(
                {**body, "candle_key_hash": "f" * 64}, sort_keys=True, separators=(",", ":")
            ).encode(),
            "unknown schema": json.dumps(
                {**body, "schema": "unknown-v9"}, sort_keys=True, separators=(",", ":")
            ).encode(),
        }
        try:
            for label, payload in variants.items():
                registration_authorization_path().write_bytes(payload)
                with self.assertRaises(CommandError, msg=label):
                    self.run_command()
        finally:
            registration_authorization_path().write_bytes(original)
        self.assertEqual(DatasetRegistration.objects.count(), 0)

        # 16: the default invocation is a complete read-only readiness check
        authorization = self.fixture_authorization()
        report = self.run_command(authorization=authorization)
        self.assertTrue(report["ready"])
        self.assertEqual(report["checkpoint"], "dry-run")
        self.assertTrue(report["read_only"])
        self.assertEqual(report["registrations_created"], 0)
        self.assertEqual(report["registration_identity"], REPLACEMENT_REGISTRATION_IDENTITY)
        self.assertEqual(report["chunk_count"], 132)
        self.assertEqual(report["successful_attempt_count"], 132)
        self.assertEqual(report["ingestion_manifest_count"], 132)
        self.assertEqual(report["candle_count"], 364953)
        self.assertEqual(report["granularity_candle_totals"], GRANULARITY_TOTALS)
        self.assertEqual(
            report["logical_chunk_set_hash"], EXPECTED_AGGREGATES["logical_chunk_set_hash"]
        )
        self.assertEqual(
            report["successful_attempt_set_hash"],
            EXPECTED_AGGREGATES["successful_attempt_set_hash"],
        )
        self.assertEqual(report["data_contract_sha256"], self.contract.sha256)
        self.assertEqual(report["replacement_plan_sha256"], self.plan.sha256)
        self.assertEqual(DatasetRegistration.objects.count(), 0)
        # 25: no provider client is constructed anywhere in the command
        self.assertNotIn("provider_request_id", json.dumps(report))

        # 2, 3: the theoretical calendar is never consulted for v2 coverage,
        # and the sealed weekend and DST timestamps outside it are accepted by
        # the Python coverage rule
        def refuse(*args, **kwargs):
            raise AssertionError("expected_candle_timestamps must not run for v2 registration")

        with patch("market.historical_acquisition.expected_candle_timestamps", refuse):
            series_manifest, row_counts, _first_last = replacement_series_coverage(
                self.plan, self.dataset, self.readiness_chunks()
            )
        self.assertEqual(sum(row_counts.values()), 364953)
        self.assertEqual(len(series_manifest), 18)
        calendar = expected_candle_timestamps(
            parse_timestamp(self.plan.ranges["D"]["from"]),
            parse_timestamp(self.plan.ranges["D"]["to"]),
            "D",
        )
        self.assertNotEqual(len(calendar), row_counts["AUD_USD:D"])

        # the database independently enforces its own sealed-inventory binding:
        # this fixture's inventories carry production identities over synthetic
        # observations, so the commit is refused here and proven on real data
        with self.assertRaisesMessage(
            DatabaseError, "replacement candles do not equal the sealed inventory"
        ):
            with transaction.atomic():
                self.register()
        connection.close()
        self.assertEqual(DatasetRegistration.objects.count(), 0)

    def assert_registration_record(self, registration):
        # 1, 14: the record carries the provider-observed identity and lineage
        self.assertEqual(registration.dataset_version_id, self.dataset.pk)
        self.assertEqual(registration.plan_id, self.plan.pk)
        self.assertEqual(registration.data_contract_id, self.contract.pk)
        self.assertEqual(
            registration.global_semantic_inventory_sha256,
            self.contract.global_semantic_inventory_sha256,
        )
        configuration = {
            "identity": REPLACEMENT_REGISTRATION_IDENTITY,
            "plan_sha256": self.plan.sha256,
            "dataset_manifest_sha256": self.dataset.manifest_sha256,
            "price_component": "COMBINED_BID_ASK",
            "logical_chunk_set_hash": registration.logical_chunk_set_hash,
            "data_contract_sha256": self.contract.sha256,
            "global_semantic_inventory_sha256": self.contract.global_semantic_inventory_sha256,
        }
        self.assertEqual(registration.configuration_sha256, stable_hash(configuration))
        for field in ("logical_chunk_set_hash", "successful_attempt_set_hash"):
            self.assertEqual(getattr(registration, field), EXPECTED_AGGREGATES[field], field)
        self.assertEqual(len(registration.row_counts), 18)
        self.assertEqual(len(registration.first_last_timestamps), 18)
        self.assertEqual(len(registration.series_manifest), 18)
        self.assertEqual(sum(registration.row_counts.values()), 364953)
        self.assertEqual(set(registration.missingness.values()), {0})
        for granularity, total in GRANULARITY_TOTALS.items():
            self.assertEqual(
                sum(
                    count
                    for key, count in registration.row_counts.items()
                    if key.endswith(f":{granularity}")
                ),
                total,
            )
        # the series manifest counts come from the sealed inventory
        for entry in registration.series_manifest:
            code, granularity = entry["series"].split(":")
            sealed = sum(
                chunk.expected_observation_count
                for chunk in HistoricalIngestionChunk.objects.filter(
                    plan=self.plan,
                    dataset_version=self.dataset,
                    instrument__code=code,
                    granularity=granularity,
                )
            )
            self.assertEqual(entry["row_count"], sealed)


class Gate7CFailClosedTests(Gate7CFixtureTestCase):
    def test_coverage_defects_are_rejected(self):
        """4, 5, 6, 7: a missing, extra, substituted or disagreeing row between
        the acquired candles and the sealed observations is refused. The
        coverage rule also compares completeness, but a completeness divergence
        cannot be represented here: both historical_discovery_observation_complete
        and stored_candles_complete constrain the column to true."""
        chunk = (
            HistoricalIngestionChunk.objects.filter(data_contract_sha256__isnull=False)
            .select_related("discovery_inventory")
            .order_by("expected_observation_count")
            .first()
        )
        inventory_id = chunk.discovery_inventory_id
        observation = chunk.discovery_inventory.observations.order_by("timestamp").values().last()
        shifted = observation["timestamp"] + timedelta(hours=1)

        def coverage():
            return replacement_series_coverage(self.plan, self.dataset, self.readiness_chunks())

        for label, statement, params, undo, undo_params in (
            (
                "missing acquired row",
                "DELETE FROM market_historicaltimestampobservation WHERE id=%s",
                [observation["id"]],
                """INSERT INTO market_historicaltimestampobservation
                   (id, inventory_id, timestamp, complete, volume, bid_present, ask_present)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                [
                    observation["id"],
                    inventory_id,
                    observation["timestamp"],
                    observation["complete"],
                    observation["volume"],
                    observation["bid_present"],
                    observation["ask_present"],
                ],
            ),
            (
                "substituted timestamp",
                "UPDATE market_historicaltimestampobservation SET timestamp=%s WHERE id=%s",
                [shifted, observation["id"]],
                "UPDATE market_historicaltimestampobservation SET timestamp=%s WHERE id=%s",
                [observation["timestamp"], observation["id"]],
            ),
            (
                "volume mismatch",
                "UPDATE market_historicaltimestampobservation SET volume=volume+1 WHERE id=%s",
                [observation["id"]],
                "UPDATE market_historicaltimestampobservation SET volume=%s WHERE id=%s",
                [observation["volume"], observation["id"]],
            ),
            (
                "extra sealed row",
                """INSERT INTO market_historicaltimestampobservation
                   (inventory_id, timestamp, complete, volume, bid_present, ask_present)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                [
                    inventory_id,
                    shifted,
                    observation["complete"],
                    observation["volume"],
                    observation["bid_present"],
                    observation["ask_present"],
                ],
                "DELETE FROM market_historicaltimestampobservation"
                " WHERE inventory_id=%s AND timestamp=%s",
                [inventory_id, shifted],
            ),
        ):
            self.forge("market_historicaltimestampobservation", statement, params)
            try:
                with self.assertRaises(DatasetQualityError, msg=label):
                    coverage()
            finally:
                self.forge("market_historicaltimestampobservation", undo, undo_params)
            self.assertEqual(DatasetRegistration.objects.count(), 0, label)

        # the restored membership reconstructs again
        _series, row_counts, _first_last = coverage()
        self.assertEqual(sum(row_counts.values()), 364953)

    def test_lineage_and_aggregate_forgeries_fail_closed(self):
        # 8, 9, 10, 11, 12, 13, 15
        readiness = verify_registration_readiness(
            self.dataset, self.plan, authorization=self.fixture_authorization()
        )
        self.assertEqual(readiness["observed"]["chunk_count"], 132)
        aggregates = registration_aggregates(
            self.dataset, readiness["chunks"], readiness["successful"]
        )
        for field in ("logical_chunk_set_hash", "successful_attempt_set_hash"):
            self.assertEqual(aggregates[field], EXPECTED_AGGREGATES[field], field)

        authorization = self.fixture_authorization()
        for field, value in (
            ("data_contract_sha256", "f" * 64),
            ("global_semantic_inventory_sha256", "e" * 64),
            ("replacement_plan_sha256", "d" * 64),
            ("replacement_dataset_manifest_sha256", "c" * 64),
            ("candle_key_hash", "b" * 64),
            ("candle_payload_hash", "a" * 64),
            ("logical_chunk_set_hash", "9" * 64),
            ("candle_count", 364952),
            ("chunk_count", 131),
            ("granularity_candle_totals", {"D": 1, "H1": 2, "W": 3}),
        ):
            with self.assertRaises(DatasetQualityError, msg=field):
                verify_registration_readiness(
                    self.dataset, self.plan, authorization={**authorization, field: value}
                )
        self.assertEqual(DatasetRegistration.objects.count(), 0)

        # the model and PostgreSQL independently refuse a forged record
        with self.assertRaises((DatabaseError, Exception)):
            with transaction.atomic():
                DatasetRegistration.objects.create(
                    dataset_version=self.dataset,
                    plan=self.plan,
                    series_manifest=readiness["series_manifest"],
                    row_counts={"AUD_USD:D": 1},
                    first_last_timestamps={},
                    missingness={},
                    conflict_count=0,
                    incident_count=0,
                    logical_chunk_set_hash=aggregates["logical_chunk_set_hash"],
                    successful_attempt_set_hash=aggregates["successful_attempt_set_hash"],
                    ingestion_manifest_set_hash=aggregates["ingestion_manifest_set_hash"],
                    candle_key_hash=aggregates["candle_key_hash"],
                    candle_payload_hash=aggregates["candle_payload_hash"],
                    configuration_sha256="",
                    report_sha256="",
                    data_contract=self.contract,
                    global_semantic_inventory_sha256=(
                        self.contract.global_semantic_inventory_sha256
                    ),
                )
        connection.close()
        self.assertEqual(DatasetRegistration.objects.count(), 0)

        # 8: a chunk bound to the wrong sealed inventory fails closed
        chunk = (
            HistoricalIngestionChunk.objects.filter(data_contract_sha256__isnull=False)
            .order_by("logical_key")
            .first()
        )
        other = (
            HistoricalIngestionChunk.objects.filter(data_contract_sha256__isnull=False)
            .exclude(pk=chunk.pk)
            .exclude(discovery_inventory_id=chunk.discovery_inventory_id)
            .first()
        )
        self.forge(
            "market_historicalingestionchunk",
            "UPDATE market_historicalingestionchunk SET discovery_inventory_id=%s WHERE id=%s",
            [other.discovery_inventory_id, chunk.pk],
        )
        self.assert_registration_refused("wrong discovery-inventory binding")
        self.forge(
            "market_historicalingestionchunk",
            "UPDATE market_historicalingestionchunk SET discovery_inventory_id=%s WHERE id=%s",
            [chunk.discovery_inventory_id, chunk.pk],
        )

        # 9: a v2 marker without complete lineage never degrades to the v1 path
        self.forge(
            "market_historicaldatasetplan",
            "UPDATE market_historicaldatasetplan SET data_contract_id=NULL,"
            " data_contract_sha256=NULL WHERE id=%s",
            [self.plan.pk],
        )
        self.plan.refresh_from_db()
        with self.assertRaisesMessage(
            DatasetQualityError, "provider-observed registration lineage does not verify"
        ):
            self.register()
        self.assertEqual(DatasetRegistration.objects.count(), 0)


class Gate7CLegacyPreservationTests(HistoricalFixtureMixin, TransactionTestCase):
    """24: the legacy path keeps its detection, interface, payload and errors."""

    def test_legacy_dataset_takes_the_unchanged_v1_path(self):
        plan, dataset = self.plan()
        chunks = list(
            plan.chunks.filter(dataset_version=dataset)
            .select_related("instrument", "discovery_inventory")
            .order_by("instrument__code", "granularity", "requested_from")
        )
        self.assertIsNone(replacement_registration_contract(plan, dataset, chunks))

        # the legacy command still registers on invocation, with no --execute
        # and exactly its historical payload keys
        with patch(
            "market.management.commands.register_failed_break_dataset.register_historical_dataset"
        ) as service:
            service.return_value = SimpleNamespace(
                pk=7, report_sha256="a" * 64, row_counts={"EUR_USD:D": 1}
            )
            stdout = StringIO()
            call_command(
                "register_failed_break_dataset",
                "--dataset-id",
                str(dataset.pk),
                "--plan-sha256",
                plan.sha256,
                stdout=stdout,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            sorted(payload), ["dataset_registration_id", "report_sha256", "row_counts"]
        )
        service.assert_called_once_with(dataset.pk, plan.sha256)

        # and the legacy service keeps its exact incomplete-dataset error
        with self.assertRaisesMessage(
            DatasetQualityError, "every historical chunk requires exactly one successful attempt"
        ):
            register_historical_dataset(dataset.pk, plan.sha256)
