"""Gate 8B': pre-discovery activation for the successor discovery plan.

Gate 8B froze the governed successor boundary and committed its authorization
artifact. This migration gives the database the authority to *execute* that
plan and nothing more.

The discovery execution validators are generic: none of them carries a v2
branch, so there is nothing here to generalize. What this migration adds is a
new set of positive restrictions scoped by the exact successor plan SHA, which
leave every existing plan — including the sealed v2 plan and its 133 historical
attempts — behaving precisely as before.

Authority is deliberately partial. Sealing, approval and registration stay
impossible: ``market_validate_discovery_seal_deferred`` and
``market_validate_gate5_registration`` are untouched, and the Gate 5 path still
admits only the v2 plan. A synthetically complete 132-inventory successor still
cannot seal, cannot be approved and cannot be registered. Granting that is the
separate business of the post-discovery authorization migration, written only
after the completed evidence has been independently accepted.

Nothing here trusts what an inserted row says about itself. The plan SHA and
the ordered request-manifest SHA are migration literals, and because the
generic validator already proves ``sha256 = market_sha256(payload)``,
``canonical_request_manifest_sha256 = market_sha256(canonical_request_manifest)``
and ``payload->'requests' = canonical_request_manifest``, pinning those two
digests pins all 132 governed requests byte-for-byte without embedding them.
"""

from importlib import import_module

from django.db import migrations

REQUIRED_0022_FUNCTIONS = {
    "market_acquisition_reject_truncate": ("", "75502da5ed1c59c4585c96f39120fbde"),
    "market_candleconflict_reject_mutation": ("", "7f669c1be82b32cdb408b09dae92827f"),
    "market_canonical_json": ("value jsonb", "aa43ea03a68b240dfcda6e2404c500a6"),
    "market_data_contract_reject_mutation": ("", "bf7f862b51de290e6c4d2b68888ef090"),
    "market_data_contract_reject_truncate": ("", "dab70c901ede5cf58d12356cbd24a8a3"),
    "market_dataqualityincident_reject_mutation": ("", "1d58428d31a48e46472419a7fa1c45a5"),
    "market_discovery_audit_reject_mutation": ("", "d91bbb0f631c2f39f8bcb229e16cd656"),
    "market_discovery_audit_reject_truncate": ("", "b5b0de2bd49976d91725d85295861ad3"),
    "market_discovery_operational_timestamp": (
        "value timestamp with time zone",
        "0ade13a9b0800de89465ec203f3a6f45",
    ),
    "market_discovery_plan_xact_lock": ("plan_key bigint", "049915d1c7640a273f7c1946d90c272a"),
    "market_discovery_reject_mutation": ("", "92d96335c5a444cfdb531c1423310a80"),
    "market_discovery_reject_sealed_insert": ("", "1c07d17226742eb2e6822f3d37052d47"),
    "market_discovery_reject_truncate": ("", "967b6921befcaf664b08f7456f5dc27d"),
    "market_discovery_structural_diagnostics_valid": (
        "diagnostics jsonb, fetched integer",
        "4a587767d6def1327aa0f65e2bc6d845",
    ),
    "market_discovery_supersession_reject_mutation": ("", "ffdd7694b355279f9caf69aa15c00db9"),
    "market_discovery_supersession_reject_truncate": ("", "e5a8bd59d73d9862ca49fc22828920c1"),
    "market_discovery_timestamp": (
        "value timestamp with time zone",
        "b7dafb1af452f2c208f4b0c2c2ef4dc3",
    ),
    "market_enforce_acquisition_audit_completeness": ("", "9e554b31d5f0ab99cd3fe2d9f6bb72db"),
    "market_expected_count": (
        "range_start timestamp with time zone, range_end timestamp with time zone, granularity text",
        "e8bf2ac0ea45070f390dfe1e5da1bd00",
    ),
    "market_governed_candle_reject_mutation": ("", "66240159137cc9af3d42b1bfbc326eee"),
    "market_historical_evidence_insert": ("", "546539000a130eb85f1f6d0cf78cea23"),
    "market_historical_manifest_insert": ("", "5fadb1fa2a72608e95cd352866ab498f"),
    "market_historical_manifest_valid": (
        "manifest_payload jsonb, manifest_dataset_id bigint, manifest_run_id bigint",
        "ce028f93f90e82c80b7f3f174736adba",
    ),
    "market_ingestion_run_enforce": ("", "9a778ba7b8b443dc2c8298ba71ba449d"),
    "market_ingestionmanifest_reject_mutation": ("", "4255aa76032f767b34a92f3554bccf2d"),
    "market_phase2b_immutable": ("", "c26120d5ca143105a00bb9f243b3c00f"),
    "market_registered_completion": (
        "value timestamp with time zone, granularity text",
        "86e7b5a82ff427a64befc27116ea413b",
    ),
    "market_reject_audit_mutation": ("", "d424fbd8975349adca4951faf9822929"),
    "market_reject_superseded_discovery_write": ("", "add43463f7c47323fb9cb8fc3945a26e"),
    "market_sha256": ("value jsonb", "96fd2a64d0e7a49328292c13b3708d98"),
    "market_validate_acquisition_audit": ("", "f5e4851ef9caac3b31e9e095e13513e6"),
    "market_validate_acquisition_canary": (
        "attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, new_run_id bigint",
        "685cb918c33d3bf7083c923e4998cbc6",
    ),
    "market_validate_data_contract": ("", "6ede57fc63245d05cc3c668aad46ecab"),
    "market_validate_dataset_registration": ("", "9ae35e1e9f4d80c808d1b916b5ac874a"),
    "market_validate_discovery_attempt": ("", "a885693dcb97e6346ce49f9d909440fe"),
    "market_validate_discovery_audit_insert": ("", "b3c77ca417a58f608d7a869547dd3782"),
    "market_validate_discovery_chunk": ("", "c52d97167722c8845958b7b2169638f1"),
    "market_validate_discovery_inventory_deferred": ("", "cbabdd794c4287fbe37d9562bd201ded"),
    "market_validate_discovery_observation": ("", "7722c113c70b269f3df1e193d992ab09"),
    "market_validate_discovery_plan": ("", "a27d41213e8b79e8d42c298561df8baf"),
    "market_validate_discovery_provider_evidence": ("", "3ada738511255b66c867407858155038"),
    "market_validate_discovery_seal_deferred": ("", "0d94f6ed42b4c77c47acd9340b5b6f5f"),
    "market_validate_discovery_supersession": ("", "915337e93db3e0a76a21f31c35ecab6c"),
    "market_validate_discovery_terminal_run": ("", "ebbd7291f5f12c7f01f98fe29d01e5f3"),
    "market_validate_gate5_registration": ("plan_key bigint", "0537c0297d982f8d5c42549fff67ddbc"),
    "market_validate_historical_attempt": ("", "48c38076d78de68fd6d58938ea713300"),
    "market_validate_historical_chunk": ("", "04f962e41b99e572c592961191be24f1"),
    "market_validate_historical_dataset": ("", "0d44ed48266cabeb0322fc594a538d47"),
    "market_validate_historical_plan": ("", "6af26a84be89987801f710f9496a68fc"),
    "market_validate_replacement_canary_attempt": (
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, new_ingestion_run_id bigint",
        "8236775a8308605a59f7e2cc3a6823d1",
    ),
    "market_validate_replacement_chunk": (
        "chunk market_historicalingestionchunk",
        "8d0db257817e97186e228eacaf2730df",
    ),
    "market_validate_replacement_dataset": (
        "dataset market_datasetversion",
        "f846902425a93592c1c58c17feb9c33f",
    ),
    "market_validate_replacement_plan": (
        "plan market_historicaldatasetplan",
        "b781077bd602957121a79675378d6e3d",
    ),
    "market_validate_replacement_registration": (
        "reg market_datasetregistration",
        "14ce4f565660ff9d3fd760f922cbff40",
    ),
    "market_verify_replacement_canary_success": ("", "9a54240709f4b325ff7bcbfe6f5d82ab"),
}

REQUIRED_0022_TRIGGERS = {
    ("market_auditevent", "market_acquisition_audit_validate"): "f550b28cb9ccebf3adec6d2d66926951",
    ("market_auditevent", "market_auditevent_append_only"): "d6c72527049739e278a76c144db73685",
    ("market_auditevent", "market_discovery_audit_immutable"): "9e04e08b33ba7fdba47075343422c7f6",
    ("market_auditevent", "market_discovery_audit_no_truncate"): "77f26dd2ac3edc1df5eac1117ec9c4b8",
    ("market_auditevent", "market_discovery_audit_validate"): "40a061306928fdc23f5018034229acd1",
    ("market_candle", "market_candle_reject_truncate"): "2f1159288eddc4f18b98c7940a6677b9",
    ("market_candle", "market_governed_candle_append_only"): "17fba36ae1057900ca844bcf762e01bb",
    (
        "market_candleconflict",
        "market_candleconflict_append_only",
    ): "67f524f4c1380504873ec71d95897080",
    (
        "market_candleconflict",
        "market_candleconflict_reject_truncate",
    ): "a4eb24ad9bf8d402e79151df1c5afe79",
    (
        "market_candleconflict",
        "market_conflict_historical_seal",
    ): "0ffd92c9a63424b710169a3271ee9d5f",
    (
        "market_dataqualityincident",
        "market_dataqualityincident_append_only",
    ): "1cbec5562f28e78fdd021b4ba60e6608",
    (
        "market_dataqualityincident",
        "market_dataqualityincident_reject_truncate",
    ): "f642dd8087ca73830f41593d9e1098cf",
    (
        "market_dataqualityincident",
        "market_incident_historical_seal",
    ): "d59bcf989963220b179de8358ee147eb",
    (
        "market_datasetregistration",
        "market_dataset_registration_immutable",
    ): "cc3213a85b68db91792513b6b4408943",
    (
        "market_datasetregistration",
        "market_dataset_registration_validate",
    ): "5d0039ab0653226b891d95960a249836",
    (
        "market_datasetregistration",
        "market_datasetregistration_reject_truncate",
    ): "39f22c91211ace6b3b6c8af69624f734",
    (
        "market_datasetversion",
        "market_datasetversion_reject_truncate",
    ): "c1bedf48d7ad1c05a0910df51338720a",
    (
        "market_datasetversion",
        "market_historical_dataset_validate",
    ): "fb85513e36dba45c5a8d44707e058295",
    (
        "market_historicaldatacontract",
        "market_data_contract_append_only",
    ): "c160a24317c761f4419b8f0d0f56662c",
    (
        "market_historicaldatacontract",
        "market_data_contract_reject_truncate",
    ): "f27592b2a9f2414a8a75ab4b5a7cee32",
    (
        "market_historicaldatacontract",
        "market_data_contract_validate",
    ): "9cfcdadfcf0f68a4ebc9b6b9ed9e4d01",
    (
        "market_historicaldatasetplan",
        "market_historical_plan_immutable",
    ): "aadd50c474aecc04eed0fec65f923403",
    (
        "market_historicaldatasetplan",
        "market_historical_plan_validate",
    ): "25994aeb6c24a708f0e99638f423a6b4",
    (
        "market_historicaldatasetplan",
        "market_historicaldatasetplan_reject_truncate",
    ): "1b44d7995a7fecef0d62c7d039740485",
    (
        "market_historicaldiscoveryapproval",
        "market_discovery_00_superseded_approval",
    ): "273a644811076df930135fa1429378f9",
    (
        "market_historicaldiscoveryapproval",
        "market_discovery_approval_atomic",
    ): "aa290706f7435a1c60abc57b355b24d2",
    (
        "market_historicaldiscoveryapproval",
        "market_historicaldiscoveryapproval_append_only",
    ): "c844ea8660aaed503566ac1066d27451",
    (
        "market_historicaldiscoveryapproval",
        "market_historicaldiscoveryapproval_reject_truncate",
    ): "cbce844045cd2e796a1d3c535d169db3",
    (
        "market_historicaldiscoveryattempt",
        "market_discovery_00_superseded_attempt",
    ): "b649bf76c7a525ce23271f1861174ea4",
    (
        "market_historicaldiscoveryattempt",
        "market_discovery_attempt_validate",
    ): "b39fdfb53ad1ac0e994277bfd87babae",
    (
        "market_historicaldiscoveryattempt",
        "market_historicaldiscoveryattempt_append_only",
    ): "6d93c191daa3ecf9f79a881bc0e6006f",
    (
        "market_historicaldiscoveryattempt",
        "market_historicaldiscoveryattempt_reject_truncate",
    ): "60c90b63ad51933c70e16503fbc32fac",
    (
        "market_historicaldiscoverychunk",
        "market_discovery_00_superseded_chunk",
    ): "cc92aaf8e8bbd691c77fe6d83f07d634",
    (
        "market_historicaldiscoverychunk",
        "market_discovery_chunk_validate",
    ): "cd35f1ca6dd08175600f9cd8c5f6777c",
    (
        "market_historicaldiscoverychunk",
        "market_historicaldiscoverychunk_append_only",
    ): "4264f1f4413d8487d8c596f6d3b0bb3a",
    (
        "market_historicaldiscoverychunk",
        "market_historicaldiscoverychunk_reject_truncate",
    ): "20ee8e7b7426b227457766e6f6e7f421",
    (
        "market_historicaldiscoveryplan",
        "market_discovery_00_superseded_plan",
    ): "b0c14c39a6b6a30c573ed8ffc3e5c65d",
    (
        "market_historicaldiscoveryplan",
        "market_discovery_plan_seal_atomic",
    ): "c0d17766fdbcfc98a1c31858dd2df34f",
    (
        "market_historicaldiscoveryplan",
        "market_discovery_plan_validate",
    ): "142452d82dba67fa68c732da48bd8550",
    (
        "market_historicaldiscoveryplan",
        "market_historicaldiscoveryplan_reject_truncate",
    ): "fad12baa827374a0a994e58afa04bc9c",
    (
        "market_historicaldiscoveryproviderevidence",
        "market_discovery_provider_unsealed",
    ): "d088edbcea3a3308aec0af84ff7ae080",
    (
        "market_historicaldiscoveryproviderevidence",
        "market_discovery_provider_validate",
    ): "4feaf0411d227ac5cb3bd5215fbd4135",
    (
        "market_historicaldiscoveryproviderevidence",
        "market_historicaldiscoveryproviderevidence_append_only",
    ): "91f3aa96d07ec0f7c7f45034c190d506",
    (
        "market_historicaldiscoveryproviderevidence",
        "market_historicaldiscoveryproviderevidence_reject_truncate",
    ): "c545e154ea88a46e9600cb2e2cd733c7",
    (
        "market_historicaldiscoveryregistration",
        "market_discovery_00_superseded_registration",
    ): "82dd7a13041425f6500e759928a8b0bf",
    (
        "market_historicaldiscoveryregistration",
        "market_discovery_registration_atomic",
    ): "3d6b0ab734c4b8a716fd9a55b909d5ff",
    (
        "market_historicaldiscoveryregistration",
        "market_historicaldiscoveryregistration_append_only",
    ): "1b9c446f62b746f9e929a0d8be33c8a2",
    (
        "market_historicaldiscoveryregistration",
        "market_historicaldiscoveryregistration_reject_truncate",
    ): "c339f3d78175624df4a00895883ab9d9",
    (
        "market_historicaldiscoverysupersession",
        "market_discovery_supersession_immutable",
    ): "6e292f862fee0f85f35ab93ee3fdef25",
    (
        "market_historicaldiscoverysupersession",
        "market_discovery_supersession_no_truncate",
    ): "043492933102938635a8d13a0131716d",
    (
        "market_historicaldiscoverysupersession",
        "market_discovery_supersession_validate",
    ): "52fcad0a7b208c7fd9d1deb3c0cf1f95",
    (
        "market_historicalingestionattempt",
        "market_historical_attempt_immutable",
    ): "5b74259cf1bd37b6c5fc05f741214057",
    (
        "market_historicalingestionattempt",
        "market_historical_attempt_validate",
    ): "c9f2baddf307e60ce81b20a40b7242bb",
    (
        "market_historicalingestionattempt",
        "market_historicalingestionattempt_reject_truncate",
    ): "28bac9695eada30e60dcc995e92eb072",
    (
        "market_historicalingestionchunk",
        "market_historical_chunk_immutable",
    ): "7b42e53ac118f446d0324e8a0f95aa6e",
    (
        "market_historicalingestionchunk",
        "market_historical_chunk_validate",
    ): "f8d13436b39a5717f50910d3c7176fcb",
    (
        "market_historicalingestionchunk",
        "market_historicalingestionchunk_reject_truncate",
    ): "6df91f25326104a361ba632e11f94264",
    (
        "market_historicaltimestampinventory",
        "market_discovery_inventory_reconstruct",
    ): "f15462f1f8ece8355c6699322eb09597",
    (
        "market_historicaltimestampinventory",
        "market_discovery_inventory_unsealed",
    ): "4f61e6b1ea7fc23a424477274bdf3f22",
    (
        "market_historicaltimestampinventory",
        "market_historicaltimestampinventory_append_only",
    ): "bacde001af1e6692466b8e1973ea9a2c",
    (
        "market_historicaltimestampinventory",
        "market_historicaltimestampinventory_reject_truncate",
    ): "5c2ff39e5ecac7cdae01ac48d0575314",
    (
        "market_historicaltimestampobservation",
        "market_discovery_observation_validate",
    ): "ab51c3031892cd203d5220471d9ee406",
    (
        "market_historicaltimestampobservation",
        "market_historicaltimestampobservation_append_only",
    ): "ec5596e660660931a76ba1a196a5541f",
    (
        "market_historicaltimestampobservation",
        "market_historicaltimestampobservation_reject_truncate",
    ): "b03d451c0a747265dbde35ca70f9d959",
    (
        "market_ingestionmanifest",
        "market_ingestion_manifest_historical_validate",
    ): "322165e08c173ca45734dcc955dc9387",
    (
        "market_ingestionmanifest",
        "market_ingestionmanifest_append_only",
    ): "643c095bbab6fa4fcf6ea6e1eb4bbb34",
    (
        "market_ingestionmanifest",
        "market_ingestionmanifest_reject_truncate",
    ): "73fbe90172c004fb1d927fd9954db673",
    (
        "market_ingestionrun",
        "market_acquisition_audit_complete",
    ): "64d9af1e7805a007ecf7636efcb0898c",
    ("market_ingestionrun", "market_discovery_run_terminal"): "f7fac0b7a1b393de30461d5dfc89c978",
    ("market_ingestionrun", "market_ingestion_run_enforce"): "ee6b757a9e76e7e25a90c1f809e85fa6",
    (
        "market_ingestionrun",
        "market_ingestionrun_reject_truncate",
    ): "fa233969980ace3a0387012b99ffe59d",
    (
        "market_oandainstrumenttermssnapshot",
        "market_oandainstrumenttermssnapshot_immutable",
    ): "ba6370e8fcef633d5034b5423d1011d8",
}

SUCCESSOR_PLAN_IDENTITY = "failed-break-phase-2b1r-discovery-plan-v3"
SUCCESSOR_PLAN_VERSION = "phase-2b1r-discovery-v3"
SUCCESSOR_PLAN_SHA256 = "e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88"
SUCCESSOR_MANIFEST_SHA256 = "6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0"
SUCCESSOR_H1_REQUESTED_FROM = "2009-12-30T22:00:00Z"
PREDECESSOR_H1_REQUESTED_FROM = "2009-12-31 15:00:00+00"
SUCCESSOR_CHUNK_COUNT = 132
SUCCESSOR_CANARY_INSTRUMENT = "AUD_USD"
MINIMUM_EARLIER_OBSERVATIONS = 6

# The two functions this migration must leave exactly as 0022 installed them.
# Sealing and Gate 5 registration remain closed to the successor.
PROTECTED_FUNCTIONS = (
    "market_validate_discovery_seal_deferred",
    "market_validate_gate5_registration",
)

DISCOVERY_PLAN_SIGNATURE = "market_validate_discovery_plan()"
DISCOVERY_ATTEMPT_SIGNATURE = "market_validate_discovery_attempt()"
SUCCESSOR_COMPLETE_SIGNATURE = "market_validate_successor_plan_complete()"

SUCCESSOR_TRIGGERS = (
    ("market_successor_plan_complete", "market_historicaldiscoveryplan"),
    ("market_successor_chunk_complete", "market_historicaldiscoverychunk"),
)

PRIOR_DISCOVERY_PLAN_PROSRC = r"""
        DECLARE approval_count integer; registration_count integer; chunk_count integer;
                materialized_manifest jsonb; source record;
        BEGIN
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'historical discovery plans are append-only';
          END IF;
          IF TG_OP='UPDATE' THEN
            IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL
               OR ROW(OLD.identity,OLD.version,OLD.source_id,OLD.purpose,OLD.environment,
                      OLD.phase1_spec_hash,OLD.phase1_manifest_hash,OLD.superseded_data_identity,
                      OLD.declared_chunk_count,OLD.canonical_request_manifest,
                      OLD.canonical_request_manifest_sha256,OLD.payload,OLD.sha256,OLD.created_at)
                  IS DISTINCT FROM
                  ROW(NEW.identity,NEW.version,NEW.source_id,NEW.purpose,NEW.environment,
                      NEW.phase1_spec_hash,NEW.phase1_manifest_hash,NEW.superseded_data_identity,
                      NEW.declared_chunk_count,NEW.canonical_request_manifest,
                      NEW.canonical_request_manifest_sha256,NEW.payload,NEW.sha256,NEW.created_at)
            THEN RAISE EXCEPTION 'only governed discovery-plan sealing is permitted'; END IF;
            SELECT count(*) INTO approval_count FROM market_historicaldiscoveryapproval
              WHERE plan_id=NEW.id;
            SELECT count(*) INTO registration_count FROM market_historicaldiscoveryregistration
              WHERE plan_id=NEW.id AND registered_at=NEW.sealed_at;
            IF approval_count<>1 OR registration_count<>1 THEN
              RAISE EXCEPTION 'discovery sealing requires atomic approval and registration';
            END IF;
            SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
              'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
              'canonical_request',c.canonical_request,
              'canonical_request_sha256',c.canonical_request_sha256) ORDER BY c.ordinal),'[]')
              INTO chunk_count,materialized_manifest FROM market_historicaldiscoverychunk c
              WHERE c.plan_id=NEW.id;
            IF chunk_count<>NEW.declared_chunk_count
               OR materialized_manifest IS DISTINCT FROM NEW.canonical_request_manifest THEN
              RAISE EXCEPTION 'materialized discovery requests do not equal declared manifest';
            END IF;
            RETURN NEW;
          END IF;
          SELECT * INTO STRICT source FROM market_sourceregistry WHERE id=NEW.source_id;
          IF NEW.sealed_at IS NOT NULL
             OR length(btrim(NEW.identity))=0
             OR NEW.version!~'^phase-2b1r-discovery-v[1-9][0-9]*$'
             OR NEW.purpose<>'provider_timestamp_inventory_discovery'
             OR NEW.environment<>'practice'
             OR NEW.phase1_spec_hash<>'47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash<>'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR NEW.superseded_data_identity<>'oanda-ba-ny17-friday-v1'
             OR jsonb_typeof(NEW.canonical_request_manifest)<>'array'
             OR jsonb_array_length(NEW.canonical_request_manifest)<>NEW.declared_chunk_count
             OR NEW.canonical_request_manifest_sha256<>
                market_sha256(NEW.canonical_request_manifest)
             OR NEW.sha256<>market_sha256(NEW.payload)
             OR NEW.payload->>'discovery_contract'<>
                'oanda-provider-observed-timestamp-discovery'
             OR NEW.payload->>'discovery_version'<>NEW.version
             OR NEW.payload->>'identity'<>NEW.identity
             OR NEW.payload->>'purpose'<>NEW.purpose
             OR NEW.payload->>'environment'<>NEW.environment
             OR NEW.payload->>'phase1_spec_hash'<>NEW.phase1_spec_hash
             OR NEW.payload->>'phase1_manifest_hash'<>NEW.phase1_manifest_hash
             OR NEW.payload->>'superseded_data_identity'<>NEW.superseded_data_identity
             OR NEW.payload->>'replacement_data_identity'<>
                'oanda-ba-ny17-friday-provider-observed-v1'
             OR (NEW.payload->>'declared_chunk_count')::integer<>NEW.declared_chunk_count
             OR NEW.payload->'requests'<>NEW.canonical_request_manifest
             OR NEW.payload->>'canonical_request_manifest_sha256'<>
                NEW.canonical_request_manifest_sha256
             OR NEW.payload->'source'<>
                '{"name":"OANDA v20","governed_identity":"oanda-v20-market-candles-v1"}'::jsonb
             OR source.name<>'OANDA v20' OR source.tier<>'established' OR NOT source.enabled
             OR source.acquisition_method<>'v20 REST API' OR source.llm_processing_allowed
          THEN RAISE EXCEPTION 'discovery plan conflicts with canonical contract'; END IF;
          RETURN NEW;
        END """

SUCCESSOR_DISCOVERY_PLAN_PROSRC = r"""
        DECLARE approval_count integer; registration_count integer; chunk_count integer;
                materialized_manifest jsonb; source record;
        BEGIN
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'historical discovery plans are append-only';
          END IF;
          IF TG_OP='UPDATE' THEN
            IF OLD.sealed_at IS NOT NULL OR NEW.sealed_at IS NULL
               OR ROW(OLD.identity,OLD.version,OLD.source_id,OLD.purpose,OLD.environment,
                      OLD.phase1_spec_hash,OLD.phase1_manifest_hash,OLD.superseded_data_identity,
                      OLD.declared_chunk_count,OLD.canonical_request_manifest,
                      OLD.canonical_request_manifest_sha256,OLD.payload,OLD.sha256,OLD.created_at)
                  IS DISTINCT FROM
                  ROW(NEW.identity,NEW.version,NEW.source_id,NEW.purpose,NEW.environment,
                      NEW.phase1_spec_hash,NEW.phase1_manifest_hash,NEW.superseded_data_identity,
                      NEW.declared_chunk_count,NEW.canonical_request_manifest,
                      NEW.canonical_request_manifest_sha256,NEW.payload,NEW.sha256,NEW.created_at)
            THEN RAISE EXCEPTION 'only governed discovery-plan sealing is permitted'; END IF;
            SELECT count(*) INTO approval_count FROM market_historicaldiscoveryapproval
              WHERE plan_id=NEW.id;
            SELECT count(*) INTO registration_count FROM market_historicaldiscoveryregistration
              WHERE plan_id=NEW.id AND registered_at=NEW.sealed_at;
            IF approval_count<>1 OR registration_count<>1 THEN
              RAISE EXCEPTION 'discovery sealing requires atomic approval and registration';
            END IF;
            SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
              'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
              'canonical_request',c.canonical_request,
              'canonical_request_sha256',c.canonical_request_sha256) ORDER BY c.ordinal),'[]')
              INTO chunk_count,materialized_manifest FROM market_historicaldiscoverychunk c
              WHERE c.plan_id=NEW.id;
            IF chunk_count<>NEW.declared_chunk_count
               OR materialized_manifest IS DISTINCT FROM NEW.canonical_request_manifest THEN
              RAISE EXCEPTION 'materialized discovery requests do not equal declared manifest';
            END IF;
            RETURN NEW;
          END IF;
          SELECT * INTO STRICT source FROM market_sourceregistry WHERE id=NEW.source_id;
          IF NEW.sealed_at IS NOT NULL
             OR length(btrim(NEW.identity))=0
             OR NEW.version!~'^phase-2b1r-discovery-v[1-9][0-9]*$'
             OR NEW.purpose<>'provider_timestamp_inventory_discovery'
             OR NEW.environment<>'practice'
             OR NEW.phase1_spec_hash<>'47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash<>'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR NEW.superseded_data_identity<>'oanda-ba-ny17-friday-v1'
             OR jsonb_typeof(NEW.canonical_request_manifest)<>'array'
             OR jsonb_array_length(NEW.canonical_request_manifest)<>NEW.declared_chunk_count
             OR NEW.canonical_request_manifest_sha256<>
                market_sha256(NEW.canonical_request_manifest)
             OR NEW.sha256<>market_sha256(NEW.payload)
             OR NEW.payload->>'discovery_contract'<>
                'oanda-provider-observed-timestamp-discovery'
             OR NEW.payload->>'discovery_version'<>NEW.version
             OR NEW.payload->>'identity'<>NEW.identity
             OR NEW.payload->>'purpose'<>NEW.purpose
             OR NEW.payload->>'environment'<>NEW.environment
             OR NEW.payload->>'phase1_spec_hash'<>NEW.phase1_spec_hash
             OR NEW.payload->>'phase1_manifest_hash'<>NEW.phase1_manifest_hash
             OR NEW.payload->>'superseded_data_identity'<>NEW.superseded_data_identity
             OR NEW.payload->>'replacement_data_identity'<>
                'oanda-ba-ny17-friday-provider-observed-v1'
             OR (NEW.payload->>'declared_chunk_count')::integer<>NEW.declared_chunk_count
             OR NEW.payload->'requests'<>NEW.canonical_request_manifest
             OR NEW.payload->>'canonical_request_manifest_sha256'<>
                NEW.canonical_request_manifest_sha256
             OR NEW.payload->'source'<>
                '{"name":"OANDA v20","governed_identity":"oanda-v20-market-candles-v1"}'::jsonb
             OR source.name<>'OANDA v20' OR source.tier<>'established' OR NOT source.enabled
             OR source.acquisition_method<>'v20 REST API' OR source.llm_processing_allowed
          THEN RAISE EXCEPTION 'discovery plan conflicts with canonical contract'; END IF;
          IF NEW.identity='failed-break-phase-2b1r-discovery-plan-v3'
             OR NEW.version='phase-2b1r-discovery-v3'
             OR NEW.sha256='e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88'
             OR NEW.canonical_request_manifest_sha256=
                '6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0'
          THEN
            IF NEW.identity<>'failed-break-phase-2b1r-discovery-plan-v3'
               OR NEW.version<>'phase-2b1r-discovery-v3'
               OR NEW.sha256<>'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88'
               OR NEW.canonical_request_manifest_sha256<>
                  '6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0'
               OR NEW.declared_chunk_count<>132
            THEN RAISE EXCEPTION
              'successor discovery plan markers must reconstruct the complete governed identity';
            END IF;
          END IF;
          RETURN NEW;
        END """

PRIOR_DISCOVERY_ATTEMPT_PROSRC = r"""
        DECLARE lineage record; expected_key text; expected_parameters jsonb;
                next_attempt integer;
        BEGIN
          SELECT c.*,p.source_id,p.sealed_at,i.code,r.dataset_version_id AS run_dataset,
                 r.source_id AS run_source,r.instrument_id AS run_instrument,
                 r.granularity AS run_granularity,r.requested_from AS run_from,
                 r.requested_to AS run_to,r.parameters,r.request_manifest_hash,r.status
            INTO STRICT lineage
            FROM market_historicaldiscoverychunk c
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_instrument i ON i.id=c.instrument_id
            JOIN market_ingestionrun r ON r.id=NEW.ingestion_run_id
            WHERE c.id=NEW.chunk_id;
          expected_key := 'historical-discovery-attempt:'||lineage.logical_key||':'||NEW.attempt_number;
          expected_parameters := jsonb_build_object(
            'purpose','provider_timestamp_inventory_discovery',
            'logical_discovery_key',lineage.logical_key,
            'canonical_request_sha256',lineage.canonical_request_sha256) || lineage.canonical_request;
          SELECT coalesce(max(attempt_number),0)+1 INTO next_attempt
            FROM market_historicaldiscoveryattempt WHERE chunk_id=NEW.chunk_id;
          IF lineage.sealed_at IS NOT NULL OR NEW.attempt_number<>next_attempt
             OR NEW.idempotency_key<>expected_key OR lineage.run_dataset IS NOT NULL
             OR lineage.run_source<>lineage.source_id
             OR lineage.run_instrument<>lineage.instrument_id
             OR lineage.run_granularity<>lineage.granularity
             OR lineage.run_from<>lineage.requested_from OR lineage.run_to<>lineage.requested_to
             OR lineage.parameters IS DISTINCT FROM expected_parameters
             OR lineage.request_manifest_hash<>market_sha256(jsonb_build_object(
                'purpose','provider_timestamp_inventory_discovery',
                'attempt_idempotency_key',expected_key))
             OR lineage.status<>'running'
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt a
               JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
               WHERE a.chunk_id=NEW.chunk_id AND r.status IN ('running','succeeded'))
          THEN RAISE EXCEPTION 'discovery attempt conflicts with canonical run lineage'; END IF;
          RETURN NEW;
        END """

SUCCESSOR_DISCOVERY_ATTEMPT_PROSRC = r"""
        DECLARE lineage record; expected_key text; expected_parameters jsonb;
                next_attempt integer; ready_first integer; ready_canary integer;
                is_first_h1 boolean;
        BEGIN
          SELECT c.*,p.source_id,p.sealed_at,i.code,r.dataset_version_id AS run_dataset,
                 r.source_id AS run_source,r.instrument_id AS run_instrument,
                 r.granularity AS run_granularity,r.requested_from AS run_from,
                 r.requested_to AS run_to,r.parameters,r.request_manifest_hash,r.status
            INTO STRICT lineage
            FROM market_historicaldiscoverychunk c
            JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
            JOIN market_instrument i ON i.id=c.instrument_id
            JOIN market_ingestionrun r ON r.id=NEW.ingestion_run_id
            WHERE c.id=NEW.chunk_id;
          expected_key := 'historical-discovery-attempt:'||lineage.logical_key||':'||NEW.attempt_number;
          expected_parameters := jsonb_build_object(
            'purpose','provider_timestamp_inventory_discovery',
            'logical_discovery_key',lineage.logical_key,
            'canonical_request_sha256',lineage.canonical_request_sha256) || lineage.canonical_request;
          SELECT coalesce(max(attempt_number),0)+1 INTO next_attempt
            FROM market_historicaldiscoveryattempt WHERE chunk_id=NEW.chunk_id;
          IF lineage.sealed_at IS NOT NULL OR NEW.attempt_number<>next_attempt
             OR NEW.idempotency_key<>expected_key OR lineage.run_dataset IS NOT NULL
             OR lineage.run_source<>lineage.source_id
             OR lineage.run_instrument<>lineage.instrument_id
             OR lineage.run_granularity<>lineage.granularity
             OR lineage.run_from<>lineage.requested_from OR lineage.run_to<>lineage.requested_to
             OR lineage.parameters IS DISTINCT FROM expected_parameters
             OR lineage.request_manifest_hash<>market_sha256(jsonb_build_object(
                'purpose','provider_timestamp_inventory_discovery',
                'attempt_idempotency_key',expected_key))
             OR lineage.status<>'running'
             OR EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt a
               JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
               WHERE a.chunk_id=NEW.chunk_id AND r.status IN ('running','succeeded'))
          THEN RAISE EXCEPTION 'discovery attempt conflicts with canonical run lineage'; END IF;
          IF EXISTS(SELECT 1 FROM market_historicaldiscoveryplan p
                    WHERE p.id=lineage.plan_id
                      AND p.sha256=
                          'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88') THEN
            IF NEW.attempt_number<>1 THEN RAISE EXCEPTION
              'successor discovery permits only attempt 1 for each governed chunk'; END IF;
            IF (SELECT count(*) FROM market_historicaldiscoverychunk c
                WHERE c.plan_id=lineage.plan_id)<>132 THEN RAISE EXCEPTION
              'successor discovery requires its complete authorized 132-chunk plan'; END IF;
            IF EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt a
                      JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                      JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
                      WHERE c.plan_id=lineage.plan_id AND r.status='running') THEN RAISE EXCEPTION
              'a successor discovery attempt is already running'; END IF;
            IF EXISTS(SELECT 1 FROM market_historicaldiscoveryattempt a
                      JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                      JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
                      WHERE c.plan_id=lineage.plan_id
                        AND r.status IN ('failed','quarantined')) THEN RAISE EXCEPTION
              'a failed successor discovery attempt permanently stops this plan'; END IF;
            SELECT count(*) INTO ready_first
              FROM market_historicaldiscoverychunk c
              JOIN market_historicaldiscoveryattempt a
                ON a.chunk_id=c.id AND a.attempt_number=1
              JOIN market_ingestionrun r
                ON r.id=a.ingestion_run_id AND r.status='succeeded'
              JOIN market_historicaltimestampinventory inv ON inv.chunk_id=c.id
              WHERE c.plan_id=lineage.plan_id AND c.granularity='H1'
                AND c.canonical_request->>'from'='2009-12-30T22:00:00Z'
                AND (SELECT count(*) FROM market_historicaltimestampobservation o
                     WHERE o.inventory_id=inv.id
                       AND o.timestamp<timestamptz '2009-12-31 15:00:00+00')>=6;
            SELECT count(*) INTO ready_canary
              FROM market_historicaldiscoverychunk c
              JOIN market_instrument ci ON ci.id=c.instrument_id
              JOIN market_historicaldiscoveryattempt a
                ON a.chunk_id=c.id AND a.attempt_number=1
              JOIN market_ingestionrun r
                ON r.id=a.ingestion_run_id AND r.status='succeeded'
              JOIN market_historicaltimestampinventory inv ON inv.chunk_id=c.id
              WHERE c.plan_id=lineage.plan_id AND c.granularity='H1'
                AND c.canonical_request->>'from'='2009-12-30T22:00:00Z'
                AND ci.code='AUD_USD'
                AND (SELECT count(*) FROM market_historicaltimestampobservation o
                     WHERE o.inventory_id=inv.id
                       AND o.timestamp<timestamptz '2009-12-31 15:00:00+00')>=6;
            is_first_h1 := lineage.granularity='H1'
              AND lineage.canonical_request->>'from'='2009-12-30T22:00:00Z';
            IF is_first_h1 AND lineage.code='AUD_USD' THEN
              NULL;
            ELSIF is_first_h1 THEN
              IF ready_canary<>1 THEN RAISE EXCEPTION
                'gate 8D1 requires the governed canary to have succeeded with at least six'
                ' additional eligible observations'; END IF;
            ELSE
              IF ready_first<>6 THEN RAISE EXCEPTION
                'gate 8D2 requires all six governed first-H1 inventories to have succeeded with'
                ' at least six additional eligible observations each'; END IF;
            END IF;
          END IF;
          RETURN NEW;
        END """

SUCCESSOR_PLAN_COMPLETE_PROSRC = r"""
        DECLARE plan_row record; chunk_total integer; materialized jsonb;
                d_total integer; h1_total integer; w_total integer;
                extended_total integer; instrument_total integer; uneven integer;
                plan_key bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key:=NEW.id;
          ELSE
            plan_key:=NEW.plan_id;
          END IF;
          SELECT * INTO plan_row FROM market_historicaldiscoveryplan WHERE id=plan_key;
          IF plan_row.id IS NULL
             OR plan_row.sha256<>
                'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88' THEN
            RETURN NULL;
          END IF;
          SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
                   'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
                   'canonical_request',c.canonical_request,
                   'canonical_request_sha256',c.canonical_request_sha256)
                 ORDER BY c.ordinal),'[]')
            INTO chunk_total,materialized
            FROM market_historicaldiscoverychunk c WHERE c.plan_id=plan_row.id;
          IF chunk_total<>132
             OR materialized IS DISTINCT FROM plan_row.canonical_request_manifest
             OR market_sha256(materialized)<>
                '6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0'
          THEN RAISE EXCEPTION
            'successor discovery plan requires exactly its 132 authorized chunks'; END IF;
          SELECT count(*) FILTER (WHERE c.granularity='D'),
                 count(*) FILTER (WHERE c.granularity='H1'),
                 count(*) FILTER (WHERE c.granularity='W'),
                 count(*) FILTER (WHERE c.granularity='H1'
                   AND c.canonical_request->>'from'='2009-12-30T22:00:00Z'),
                 count(DISTINCT c.instrument_id)
            INTO d_total,h1_total,w_total,extended_total,instrument_total
            FROM market_historicaldiscoverychunk c WHERE c.plan_id=plan_row.id;
          SELECT count(*) INTO uneven FROM (
            SELECT c.instrument_id FROM market_historicaldiscoverychunk c
             WHERE c.plan_id=plan_row.id
             GROUP BY c.instrument_id
            HAVING count(*) FILTER (WHERE c.granularity='D')<>1
                OR count(*) FILTER (WHERE c.granularity='H1')<>20
                OR count(*) FILTER (WHERE c.granularity='W')<>1) skewed;
          IF d_total<>6 OR h1_total<>120 OR w_total<>6 OR extended_total<>6
             OR instrument_total<>6 OR uneven<>0
          THEN RAISE EXCEPTION
            'successor discovery plan shape does not reconstruct'; END IF;
          RETURN NULL;
        END
"""

SUCCESSOR_ROW_TABLES = (
    ("market_historicaldiscoverychunk", "plan_id"),
    ("market_historicaldiscoveryattempt", None),
)


def _execute(cursor, statement):
    cursor.execute(statement.replace("%", "%%"))


def _install(cursor, signature, returns, body):
    _execute(
        cursor,
        f"CREATE OR REPLACE FUNCTION {signature} RETURNS {returns} AS $governed${body}$governed$"
        " LANGUAGE plpgsql",
    )


def _installed_body(cursor, name):
    cursor.execute(
        "SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
        " WHERE n.nspname=current_schema() AND p.proname=%s",
        [name],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"governed function {name} is missing or ambiguous")
    return rows[0][0]


def _fingerprints(cursor):
    governance = import_module("market.migrations.0014_historical_discovery_supersession")
    cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0022_FUNCTIONS)])
    functions = {}
    for name, arguments, fingerprint in cursor.fetchall():
        functions.setdefault(name, []).append((arguments, fingerprint))
    cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
    triggers = {}
    for table, name, fingerprint in cursor.fetchall():
        triggers.setdefault((table, name), []).append(fingerprint)
    return functions, triggers


def _preflight(cursor):
    """The complete installed 0022 catalog, or nothing happens."""
    cursor.execute(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
        " WHERE n.nspname=current_schema() AND p.proname='market_validate_successor_plan_complete'"
    )
    if cursor.fetchone()[0]:
        raise RuntimeError("the successor completeness validator is already installed")
    for name, table in SUCCESSOR_TRIGGERS:
        cursor.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid"
            " WHERE NOT t.tgisinternal AND c.relname=%s AND t.tgname=%s",
            [table, name],
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(f"successor trigger {name} is already installed")
    functions, triggers = _fingerprints(cursor)
    for name, expected in REQUIRED_0022_FUNCTIONS.items():
        found = functions.get(name, [])
        if len(found) != 1:
            raise RuntimeError(f"required 0022 function {name} is missing or ambiguous")
        if found[0] != tuple(expected):
            raise RuntimeError(f"required 0022 function {name} does not match its 0022 definition")
    cursor.execute(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
        " WHERE n.nspname=current_schema() AND p.proname LIKE 'market\\_%'"
    )
    for (name,) in cursor.fetchall():
        if name not in REQUIRED_0022_FUNCTIONS:
            raise RuntimeError(f"unexpected function {name} in the governed catalog")
    for key, expected in REQUIRED_0022_TRIGGERS.items():
        found = triggers.get(key, [])
        if len(found) != 1:
            raise RuntimeError(
                f"required 0022 trigger {key[1]} on {key[0]} is missing or ambiguous"
            )
        if found[0] != expected:
            raise RuntimeError(
                f"required 0022 trigger {key[1]} on {key[0]} does not match its 0022 definition"
            )
    for key in triggers:
        if key[0].startswith("market_") and key not in REQUIRED_0022_TRIGGERS:
            raise RuntimeError(f"unexpected trigger {key[1]} on {key[0]}")
    if _installed_body(cursor, "market_validate_discovery_plan") != PRIOR_DISCOVERY_PLAN_PROSRC:
        raise RuntimeError("installed discovery-plan validator does not match its 0022 definition")
    if (
        _installed_body(cursor, "market_validate_discovery_attempt")
        != PRIOR_DISCOVERY_ATTEMPT_PROSRC
    ):
        raise RuntimeError(
            "installed discovery-attempt validator does not match its 0022 definition"
        )


def _protected_bodies(cursor):
    return {name: _installed_body(cursor, name) for name in PROTECTED_FUNCTIONS}


def _successor_evidence(cursor):
    """Any persisted successor row at all — plan, chunk, attempt, evidence,
    observation or inventory."""
    cursor.execute(
        """
        SELECT count(*) FROM market_historicaldiscoveryplan p
         WHERE p.sha256=%s OR p.identity=%s OR p.version=%s
        """,
        [SUCCESSOR_PLAN_SHA256, SUCCESSOR_PLAN_IDENTITY, SUCCESSOR_PLAN_VERSION],
    )
    if cursor.fetchone()[0]:
        return True
    cursor.execute(
        """
        SELECT count(*) FROM market_historicaldiscoverychunk c
          JOIN market_historicaldiscoveryplan p ON p.id=c.plan_id
         WHERE p.sha256=%s
        """,
        [SUCCESSOR_PLAN_SHA256],
    )
    return bool(cursor.fetchone()[0])


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _preflight(cursor)
        protected = _protected_bodies(cursor)
        _install(cursor, DISCOVERY_PLAN_SIGNATURE, "trigger", SUCCESSOR_DISCOVERY_PLAN_PROSRC)
        _install(cursor, DISCOVERY_ATTEMPT_SIGNATURE, "trigger", SUCCESSOR_DISCOVERY_ATTEMPT_PROSRC)
        _install(cursor, SUCCESSOR_COMPLETE_SIGNATURE, "trigger", SUCCESSOR_PLAN_COMPLETE_PROSRC)
        for name, table in SUCCESSOR_TRIGGERS:
            _execute(
                cursor,
                f"CREATE CONSTRAINT TRIGGER {name} AFTER INSERT ON {table}"
                " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
                " EXECUTE FUNCTION market_validate_successor_plan_complete()",
            )
        if _protected_bodies(cursor) != protected:
            raise RuntimeError("gate 8B-prime must not alter sealing or registration governance")


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _successor_evidence(cursor):
            raise RuntimeError("successor discovery evidence prohibits gate 8B-prime reversal")
        protected = _protected_bodies(cursor)
        for name, table in SUCCESSOR_TRIGGERS:
            _execute(cursor, f"DROP TRIGGER IF EXISTS {name} ON {table}")
        _execute(cursor, "DROP FUNCTION IF EXISTS market_validate_successor_plan_complete()")
        _install(cursor, DISCOVERY_PLAN_SIGNATURE, "trigger", PRIOR_DISCOVERY_PLAN_PROSRC)
        _install(cursor, DISCOVERY_ATTEMPT_SIGNATURE, "trigger", PRIOR_DISCOVERY_ATTEMPT_PROSRC)
        if _installed_body(cursor, "market_validate_discovery_plan") != PRIOR_DISCOVERY_PLAN_PROSRC:
            raise RuntimeError("gate 8B-prime reversal did not restore the plan validator")
        if (
            _installed_body(cursor, "market_validate_discovery_attempt")
            != PRIOR_DISCOVERY_ATTEMPT_PROSRC
        ):
            raise RuntimeError("gate 8B-prime reversal did not restore the attempt validator")
        if _protected_bodies(cursor) != protected:
            raise RuntimeError("gate 8B-prime reversal must not alter protected governance")


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("market", "0022_provider_observed_registration_validator_correction")]

    operations = [migrations.RunPython(forward, reverse)]
