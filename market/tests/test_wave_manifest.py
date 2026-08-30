import json
from collections import Counter
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase

from market.discovery_waves import (
    PROPOSED_LATER_WAVE_SIZE,
    REMAINING_CHUNK_COUNT,
    WAVE_MANIFEST_SCHEMA_IDENTITY,
    build_wave_manifest,
)
from market.historical_discovery import (
    CANARY_SEMANTIC_INVENTORY_SHA256_RECORDED,
    CANARY_V2_LOGICAL_KEY,
    DISCOVERY_V2_MANIFEST_SHA256,
    DISCOVERY_V2_PLAN_SHA256,
    build_replacement_discovery_plan,
    canonical_hash,
)

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "strategy"
    / "failed-break"
    / "v1"
    / "phase-2b1r-gate4-wave-manifest.json"
)


class WaveManifestTests(SimpleTestCase):
    def test_manifest_is_deterministic_and_canonically_ordered(self):
        first = build_wave_manifest("a" * 64)
        second = build_wave_manifest("a" * 64)
        self.assertEqual(first, second)
        self.assertEqual(first["schema_identity"], WAVE_MANIFEST_SCHEMA_IDENTITY)
        self.assertEqual(first["v2_plan_sha256"], DISCOVERY_V2_PLAN_SHA256)
        self.assertEqual(first["v2_manifest_sha256"], DISCOVERY_V2_MANIFEST_SHA256)
        self.assertEqual(first["chunk_count"], REMAINING_CHUNK_COUNT)
        self.assertEqual(len(first["chunks"]), 131)
        ordinals = [chunk["ordinal"] for chunk in first["chunks"]]
        self.assertEqual(ordinals, sorted(ordinals))
        self.assertEqual(first["ordered_manifest_sha256"], canonical_hash(first["chunks"]))

    def test_manifest_covers_exactly_the_remaining_chunks(self):
        manifest = build_wave_manifest("b" * 64)
        plan = build_replacement_discovery_plan()
        expected_keys = [
            item["logical_discovery_key"]
            for item in plan["requests"]
            if item["logical_discovery_key"] != CANARY_V2_LOGICAL_KEY
        ]
        manifest_keys = [chunk["logical_key"] for chunk in manifest["chunks"]]
        self.assertEqual(manifest_keys, expected_keys)
        self.assertEqual(len(set(manifest_keys)), 131)
        self.assertNotIn(CANARY_V2_LOGICAL_KEY, manifest_keys)
        by_key = {item["logical_discovery_key"]: item for item in plan["requests"]}
        for chunk in manifest["chunks"]:
            source = by_key[chunk["logical_key"]]
            request = source["canonical_request"]
            self.assertEqual(chunk["ordinal"], source["ordinal"])
            self.assertEqual(chunk["canonical_request_sha256"], source["canonical_request_sha256"])
            self.assertEqual(chunk["instrument"], request["instrument"])
            self.assertEqual(chunk["granularity"], request["granularity"])
            self.assertEqual(chunk["requested_from"], request["from"])
            self.assertEqual(chunk["requested_to"], request["to"])

    def test_wave_grouping_matches_the_approved_operational_shape(self):
        manifest = build_wave_manifest("c" * 64)
        waves = Counter(chunk["wave_number"] for chunk in manifest["chunks"])
        self.assertEqual(dict(waves), {1: 17, 2: 24, 3: 24, 4: 24, 5: 24, 6: 18})
        self.assertEqual(manifest["proposed_later_wave_size"], PROPOSED_LATER_WAVE_SIZE)
        wave_one = [c for c in manifest["chunks"] if c["wave_number"] == 1]
        self.assertEqual(Counter(c["granularity"] for c in wave_one), {"D": 6, "W": 6, "H1": 5})
        self.assertEqual(
            sorted(c["instrument"] for c in wave_one if c["granularity"] == "H1"),
            ["EUR_GBP", "EUR_USD", "GBP_USD", "USD_CAD", "USD_JPY"],
        )
        later = [c for c in manifest["chunks"] if c["wave_number"] > 1]
        self.assertEqual([c["ordinal"] for c in later], sorted(c["ordinal"] for c in later))

    def test_committed_artifact_matches_the_recorded_canary_rendering(self):
        rendered = StringIO()
        call_command(
            "report_discovery_wave_manifest",
            "--canary-semantic-inventory-sha256",
            CANARY_SEMANTIC_INVENTORY_SHA256_RECORDED,
            stdout=rendered,
        )
        self.assertEqual(ARTIFACT_PATH.read_text(encoding="utf-8"), rendered.getvalue())
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(artifact, build_wave_manifest(CANARY_SEMANTIC_INVENTORY_SHA256_RECORDED))

    def test_artifact_is_secret_free(self):
        blob = ARTIFACT_PATH.read_text(encoding="utf-8")
        for marker in ("Authorization", "Bearer", "https://", "account", "token", '"o":'):
            self.assertNotIn(marker, blob)
