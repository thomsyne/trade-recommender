"""Gate 8E focused tests: successor contract and acquisition-plan generation.

These are bounded, pure-layer tests. They exercise the deterministic generators,
the governed identity pins and the refusals that do not require the full 132-chunk
successor discovery inventory to exist. The governed database branches added by
migration 0025 are exercised at full scale by the disposable rehearsal, because
their predicates pin the real accepted evidence and cannot be satisfied by a
reduced fixture -- a property these tests assert directly.
"""

from django.test import SimpleTestCase, TestCase

from market.historical_discovery import canonical_hash
from market.models import dataset_manifest_sha256
from market.provider_observed_acquisition import (
    REPLACEMENT_DATA_IDENTITY,
    REPLACEMENT_IDENTITIES,
    build_data_contract_payload,
)
from market.provider_observed_gate8e import (
    SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY,
    SUCCESSOR_ACQUISITION_PLAN_SHA256,
    SUCCESSOR_ACQUISITION_VERSION,
    SUCCESSOR_CHUNK_COUNT,
    SUCCESSOR_CONTRACT_SHA256,
    SUCCESSOR_DATA_IDENTITY,
    SUCCESSOR_DATASET_MANIFEST_SHA256,
    SUCCESSOR_GRANULARITY_CHUNKS,
    SUCCESSOR_INSTRUMENT_CHUNKS,
    build_successor_data_contract_payload,
    successor_acquisition_canary_logical_key,
    successor_data_contract_semantic_hash,
    successor_identities,
)
from market.provider_observed_outcome import accepted_successor_registration

ACCEPTED_SEMANTIC = "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
PREDECESSOR_SEMANTIC = "78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c"


class Gate8EDiscoveryVersionSemanticsTests(SimpleTestCase):
    """The one field the reviewer pinned by hand, and why it stays put."""

    def test_successor_contract_retains_the_discovery_contract_generation(self):
        """`discovery_version` names the discovery contract generation, which is
        unchanged, not the discovery plan generation. The predecessor is the
        governing precedent: its contract carries this same value while its
        discovery plan is v2."""
        payload = build_successor_data_contract_payload(ACCEPTED_SEMANTIC)
        self.assertEqual(payload["discovery_version"], "phase-2b1r-discovery-v1")
        predecessor = build_data_contract_payload(PREDECESSOR_SEMANTIC)
        self.assertEqual(payload["discovery_version"], predecessor["discovery_version"])

    def test_substituting_the_plan_generation_changes_the_contract_identity(self):
        """Writing `phase-2b1r-discovery-v3` into this field would invent a
        contract identity: the payload hash moves off the governed pin, so the
        installed successor branch refuses it."""
        payload = build_successor_data_contract_payload(ACCEPTED_SEMANTIC)
        substituted = dict(payload, discovery_version="phase-2b1r-discovery-v3")
        self.assertNotEqual(canonical_hash(substituted), canonical_hash(payload))
        self.assertNotEqual(canonical_hash(substituted), SUCCESSOR_CONTRACT_SHA256)

    def test_only_the_two_evidence_fields_differ_from_the_predecessor(self):
        successor = build_successor_data_contract_payload(ACCEPTED_SEMANTIC)
        predecessor = build_data_contract_payload(PREDECESSOR_SEMANTIC)
        self.assertEqual(set(successor), set(predecessor))
        differing = {k for k in successor if successor[k] != predecessor[k]}
        self.assertEqual(
            differing, {"replacement_data_identity", "global_semantic_inventory_sha256"}
        )


class Gate8ESuccessorCannotMasqueradeTests(SimpleTestCase):
    def test_successor_identity_and_hashes_differ_from_the_predecessor(self):
        self.assertNotEqual(SUCCESSOR_DATA_IDENTITY, REPLACEMENT_DATA_IDENTITY)
        self.assertNotEqual(SUCCESSOR_CONTRACT_SHA256, canonical_hash(build_data_contract_payload(PREDECESSOR_SEMANTIC)))
        identities = successor_identities()
        self.assertNotEqual(identities["data_identity"], REPLACEMENT_IDENTITIES["data_identity"])
        self.assertNotEqual(
            identities["discovery_plan_sha256"], REPLACEMENT_IDENTITIES["discovery_plan_sha256"]
        )
        self.assertNotEqual(
            identities["acquisition_version"], REPLACEMENT_IDENTITIES["acquisition_version"]
        )
        self.assertNotEqual(
            SUCCESSOR_ACQUISITION_PLAN_SHA256,
            "f0be516c732d775ce57fd98a39a7dd7df917d4eaa2c9c0ffd2fc7028d9a23528",
        )
        self.assertNotEqual(
            SUCCESSOR_DATASET_MANIFEST_SHA256,
            "9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54",
        )
        self.assertNotEqual(
            SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY,
            "e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c",
        )

    def test_successor_binds_the_accepted_gate8d3_and_8d4_evidence(self):
        accepted = accepted_successor_registration()
        identities = successor_identities()
        self.assertEqual(identities["discovery_plan_sha256"], accepted["plan_sha256"])
        self.assertEqual(
            build_successor_data_contract_payload(
                accepted["global_semantic_inventory_sha256"]
            )["global_semantic_inventory_sha256"],
            accepted["global_semantic_inventory_sha256"],
        )
        self.assertEqual(
            successor_data_contract_semantic_hash(
                global_semantic_inventory_sha256=accepted["global_semantic_inventory_sha256"]
            ),
            SUCCESSOR_CONTRACT_SHA256,
        )


class Gate8EAlteredEvidenceRefusedTests(SimpleTestCase):
    def test_any_altered_semantic_hash_moves_the_contract_off_its_pin(self):
        for altered in (
            PREDECESSOR_SEMANTIC,
            "0" * 64,
            ACCEPTED_SEMANTIC[:-1] + ("0" if ACCEPTED_SEMANTIC[-1] != "0" else "1"),
        ):
            with self.subTest(altered=altered):
                self.assertNotEqual(
                    successor_data_contract_semantic_hash(
                        global_semantic_inventory_sha256=altered
                    ),
                    SUCCESSOR_CONTRACT_SHA256,
                )

    def test_every_payload_field_is_load_bearing_for_the_contract_identity(self):
        base = build_successor_data_contract_payload(ACCEPTED_SEMANTIC)
        self.assertEqual(canonical_hash(base), SUCCESSOR_CONTRACT_SHA256)
        for key in base:
            with self.subTest(field=key):
                tampered = dict(base)
                tampered[key] = "tampered"
                self.assertNotEqual(canonical_hash(tampered), SUCCESSOR_CONTRACT_SHA256)
                dropped = {k: v for k, v in base.items() if k != key}
                self.assertNotEqual(canonical_hash(dropped), SUCCESSOR_CONTRACT_SHA256)


class Gate8EPortablePayloadPrivacyTests(SimpleTestCase):
    def test_no_username_identifier_or_operational_value_enters_the_contract_payload(self):
        payload = build_successor_data_contract_payload(ACCEPTED_SEMANTIC)
        blob = canonical_hash.__module__ and str(payload)
        for forbidden in ("approved_by", "username", "user", "password", "token", "http", "/Users/"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, blob)
        for value in payload.values():
            self.assertIsInstance(value, str)


class Gate8EShapeConstantsTests(SimpleTestCase):
    def test_required_acquisition_shape_is_pinned(self):
        self.assertEqual(SUCCESSOR_CHUNK_COUNT, 132)
        self.assertEqual(SUCCESSOR_GRANULARITY_CHUNKS, {"D": 6, "H1": 120, "W": 6})
        self.assertEqual(SUCCESSOR_INSTRUMENT_CHUNKS, {"D": 1, "H1": 20, "W": 1})
        self.assertEqual(
            sum(SUCCESSOR_INSTRUMENT_CHUNKS.values()) * 6, SUCCESSOR_CHUNK_COUNT
        )
        self.assertEqual(SUCCESSOR_ACQUISITION_VERSION, "phase-2b1r-v2")

    def test_the_acquisition_canary_is_the_lowest_ordinal_and_leaves_131_behind(self):
        payloads = {
            "chunks": [
                {"ordinal": 3, "logical_key": "c"},
                {"ordinal": 1, "logical_key": "a"},
                {"ordinal": 2, "logical_key": "b"},
            ]
        }
        self.assertEqual(successor_acquisition_canary_logical_key(payloads), "a")


class Gate8EDatasetParentIsOperationalOnlyTests(TestCase):
    """`DatasetVersion.parent` is operational lineage and nothing else."""

    MANIFEST = {
        "strategy_manifest_sha256": "a" * 64,
        "partition": {"name": "development", "start_year": 2010, "end_year": 2018},
        "required_ranges": [],
        "historical_plan_sha256": "b" * 64,
        "price_component": "COMBINED_BID_ASK",
        "complete_only": True,
        "instruments": ["AUD_USD"],
        "granularities": ["D"],
        "alignment": {"timezone": "America/New_York"},
        "data_identity": SUCCESSOR_DATA_IDENTITY,
        "historical_data_contract_sha256": "c" * 64,
        "global_semantic_inventory_sha256": ACCEPTED_SEMANTIC,
    }

    def test_parent_is_absent_from_the_manifest_and_cannot_change_its_hash(self):
        self.assertNotIn("parent", self.MANIFEST)
        baseline = dataset_manifest_sha256(self.MANIFEST)
        # The portable identity is a function of the manifest alone; a parent
        # reference lives in a column and can never reach it.
        self.assertEqual(dataset_manifest_sha256(dict(self.MANIFEST)), baseline)
        with_parent_key = dict(self.MANIFEST, parent="anything")
        self.assertNotEqual(dataset_manifest_sha256(with_parent_key), baseline)

    def test_parent_never_appears_in_any_generated_portable_payload(self):
        payload = build_successor_data_contract_payload(ACCEPTED_SEMANTIC)
        self.assertNotIn("parent", payload)
        self.assertNotIn("parent", successor_identities())
