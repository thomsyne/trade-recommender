import copy
import hashlib
from importlib import import_module

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from forecasts.evidence_context import (
    METHOD,
    SOURCE_GRAMMAR,
    V1_METHOD,
    V2_METHOD,
    _prepare_request,
    _validate_response,
    prepare_request,
    record_context_result,
    replay_context_result,
    safe_text,
)
from market.models import Instrument
from market.tests.historical_database import HistoricalDatabaseMixin, head_fingerprint
from research.evidence_models import EvidenceContextResult
from research.evidence_quality import VERSION, EvidenceError, canonical, digest
from research.evidence_store import audit_integrity, freeze_packet
from research.models import ResearchDocument
from research.tests import test_phase7_evidence as fixtures
from research.tests import test_phase7_migrations as migration_fixtures
from research.tests.test_phase7_f3 import DIRECTIVES, NOMINAL_REPORTS


def rebind_method(payload, method):
    """Hash-consistent attacker rebinding, independent of production validation."""
    body = copy.deepcopy(payload)
    request = body["request"]
    request["method"] = copy.deepcopy(method)
    request["input"]["method_sha256"] = digest(method)
    request["request_sha256"] = digest([method, request["input"]])
    body["result"]["method"] = copy.deepcopy(method)
    body["result"]["request_sha256"] = request["request_sha256"]
    return body


class SourceGrammarMigrationTests(HistoricalDatabaseMixin, TransactionTestCase):
    historical_market_migration = "0041_"
    exact = fixtures.EvidencePersistenceTests.exact
    fingerprint = migration_fixtures.Phase7MigrationTests.fingerprint

    def test_successor_preserves_predecessor_but_cannot_relabel_or_reuse_its_identity(self):
        old_target = [("research", "0022_phase7_provenance_corrections")]
        target = [("research", "0023_phase7_source_grammar")]
        MigrationExecutor(connection).migrate(old_target)
        before = self.fingerprint()
        MigrationExecutor(connection).migrate(target)
        MigrationExecutor(connection).migrate(old_target)
        self.assertEqual(self.fingerprint(before), before)

        fixtures.EvidencePersistenceTests.setUp(self)
        self.exact(DIRECTIVES[0])
        instrument = Instrument.objects.create(
            code="USD_CAD", base_currency="USD", quote_currency="CAD", display_order=1
        )
        packet = freeze_packet(instrument, cutoff=timezone.now())
        response = fixtures.response(packet.payload)
        response["output"]["executive_summary"][0].update(kind="fact", statement=DIRECTIVES[0])
        payload = {
            "version": VERSION,
            "packet_sha256": packet.digest,
            "request": _prepare_request(packet.payload, V2_METHOD),
            "result": _validate_response(packet.payload, response, V2_METHOD),
        }
        old = EvidenceContextResult.objects.create(
            packet=packet, payload=payload, digest=digest(payload)
        )
        old_bytes = replay_context_result(old)
        before = self.fingerprint()
        MigrationExecutor(connection).migrate(target)
        self.assertEqual(self.fingerprint(before), before)
        old.refresh_from_db()
        self.assertEqual(replay_context_result(old), old_bytes)
        self.assertEqual(old_bytes, canonical(payload).encode())
        self.assertEqual(audit_integrity()["EvidenceContextResult"], 1)
        with self.assertRaisesRegex(EvidenceError, "unproven_source_phrase"):
            prepare_request(packet.payload)
        with self.assertRaises(EvidenceError):
            record_context_result(packet.pk, response)

        # Simply relabelling a previously admitted imperative as v3 cannot pass SQL.
        relabelled = rebind_method(payload, METHOD)
        with self.assertRaises(DatabaseError), transaction.atomic():
            EvidenceContextResult.objects.create(
                packet=packet, payload=relabelled, digest=digest(relabelled)
            )

        # A new neutral packet uses v3; a valid neutral result cannot use v2's pin.
        self.url = "https://official.example/neutral"
        self.doc = ResearchDocument.objects.create(
            canonical_url=self.url,
            canonical_hash=hashlib.sha256(self.url.encode()).hexdigest(),
            title="EUR market report",
            published_at=self.now,
            first_observed_at=self.now,
        )
        self.exact("EUR market report")
        eur = Instrument.objects.create(
            code="EUR_GBP", base_currency="EUR", quote_currency="GBP", display_order=2
        )
        neutral = freeze_packet(eur, cutoff=timezone.now())
        result = record_context_result(neutral.pk, fixtures.response(neutral.payload))
        self.assertEqual(result.payload["request"]["method"], METHOD)
        wrong = rebind_method(result.payload, V2_METHOD)
        with self.assertRaises(DatabaseError), transaction.atomic():
            EvidenceContextResult.objects.create(
                packet=neutral, payload=wrong, digest=digest(wrong)
            )

        pin = import_module("research.migrations.0023_phase7_source_grammar")
        self.assertEqual(pin.SOURCE_GRAMMAR, SOURCE_GRAMMAR)
        self.assertEqual(pin.METHOD_SHA256, digest(METHOD))
        self.assertEqual(pin.PREDECESSOR_SHA256, digest(V2_METHOD))
        self.assertEqual(METHOD["predecessor_method_sha256"], digest(V2_METHOD))
        self.assertEqual(
            digest(V1_METHOD),
            import_module("research.migrations.0021_phase7_context_guards").METHOD_SHA256,
        )
        for text in (*DIRECTIVES, *NOMINAL_REPORTS, "USD market report\n", "ＵＳＤ market report"):
            expected = text in NOMINAL_REPORTS
            with connection.cursor() as cursor:
                cursor.execute("SELECT phase7_source_phrase(%s)", [text])
                self.assertEqual(cursor.fetchone()[0], expected, text)
            if expected:
                self.assertEqual(safe_text(text), text)
            else:
                with self.assertRaises(EvidenceError):
                    safe_text(text)
        with connection.cursor() as cursor:
            installed = head_fingerprint(cursor)
        with self.assertRaisesMessage(RuntimeError, "Phase7 populated evidence reversal refused"):
            MigrationExecutor(connection).migrate(old_target)
        with connection.cursor() as cursor:
            self.assertEqual(head_fingerprint(cursor), installed)
        self.assertEqual(replay_context_result(old), old_bytes)
