"""Gate 7C: correct the provider-observed registration validator.

The 0019 definition of market_validate_replacement_registration builds each
series_manifest row_count with a correlated subquery whose predicate reads
``c.granularity = granularity``. PostgreSQL resolves that bare name to the inner
table column, so the predicate degenerates to ``c.granularity = c.granularity``
and the granularity filter disappears: every granularity of an instrument
receives that instrument's all-granularity total. A correct provider-observed
registration therefore cannot commit.

This migration replaces exactly that one function. The lateral columns are given
unambiguous names and every reference to them is qualified, so no inner column
or PL/pgSQL variable can shadow them. Every other predicate, identity, hash
formula and ordering rule is byte-identical to the 0019 body.
"""

from importlib import import_module

from django.db import migrations

REQUIRED_0021_FUNCTIONS = {
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
        "5be441a6ad0c185ace61784d7282aecb",
    ),
    "market_verify_replacement_canary_success": ("", "9a54240709f4b325ff7bcbfe6f5d82ab"),
}
REQUIRED_0021_TRIGGERS = {
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


CORRECTED_REPLACEMENT_REGISTRATION_PROSRC = r"""
        DECLARE plan record; dataset record; contract record; expected_logical text;
                expected_attempt text; expected_manifest_hash text; expected_series jsonb;
                expected_candle_keys text; expected_candle_payloads text;
                configuration jsonb; report jsonb; bad_chunks integer; bad_series integer;
                total_expected bigint; total_candles bigint;
        BEGIN
          LOCK TABLE market_historicalingestionchunk, market_historicalingestionattempt,
            market_ingestionrun, market_ingestionmanifest, market_candle
            IN SHARE ROW EXCLUSIVE MODE;
          SELECT * INTO STRICT plan FROM market_historicaldatasetplan WHERE id=reg.plan_id;
          SELECT * INTO STRICT dataset FROM market_datasetversion
            WHERE id=reg.dataset_version_id;
          SELECT * INTO STRICT contract FROM market_historicaldatacontract
            WHERE id=plan.data_contract_id;
          SELECT market_sha256(coalesce(jsonb_agg(c.logical_key
                   ORDER BY i.code,c.granularity,c.requested_from),'[]'))
            INTO expected_logical FROM market_historicalingestionchunk c
            JOIN market_instrument i ON i.id=c.instrument_id
            WHERE c.plan_id=reg.plan_id AND c.dataset_version_id=reg.dataset_version_id;
          SELECT market_sha256(coalesce(jsonb_agg(a.idempotency_key
                   ORDER BY i.code,c.granularity,c.requested_from),'[]')),
                 market_sha256(coalesce(jsonb_agg(m.sha256 ORDER BY m.sha256),'[]'))
            INTO expected_attempt, expected_manifest_hash
            FROM market_historicalingestionchunk c
            JOIN market_historicalingestionattempt a ON a.chunk_id=c.id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id AND r.status='succeeded'
            JOIN market_ingestionmanifest m ON m.ingestion_run_id=r.id
            JOIN market_instrument i ON i.id=c.instrument_id
            WHERE c.plan_id=reg.plan_id AND c.dataset_version_id=reg.dataset_version_id;
          SELECT jsonb_agg(jsonb_build_object(
                   'series',instruments.instrument_code||':'||granularities.granularity_name,
                   'range',plan.ranges->granularities.granularity_name,
                   'row_count',(SELECT coalesce(sum(c.expected_observation_count),0)
                     FROM market_historicalingestionchunk c
                     JOIN market_instrument i ON i.id=c.instrument_id
                     WHERE c.plan_id=reg.plan_id
                       AND c.dataset_version_id=reg.dataset_version_id
                       AND i.code=instruments.instrument_code
                       AND c.granularity=granularities.granularity_name))
                   ORDER BY instruments.instrument_order,granularities.granularity_order)
            INTO expected_series
            FROM jsonb_array_elements_text(plan.instruments)
              WITH ORDINALITY instruments(instrument_code,instrument_order)
            CROSS JOIN jsonb_array_elements_text(plan.granularities)
              WITH ORDINALITY granularities(granularity_name,granularity_order);
          SELECT encode(digest(convert_to(coalesce(string_agg(market_canonical_json(jsonb_build_array(
                    i.code,c.granularity,to_char(c.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00')),
                    '' ORDER BY i.code,c.granularity,c.timestamp),''),'UTF8'),'sha256'),'hex'),
                 encode(digest(convert_to(coalesce(string_agg(market_canonical_json(jsonb_build_array(
                    i.code,c.granularity,to_char(c.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')||'+00:00',
                    c.complete,c.volume,to_char(c.bid_open,'FM999999999990.000000'),
                    to_char(c.bid_high,'FM999999999990.000000'),to_char(c.bid_low,'FM999999999990.000000'),
                    to_char(c.bid_close,'FM999999999990.000000'),to_char(c.ask_open,'FM999999999990.000000'),
                    to_char(c.ask_high,'FM999999999990.000000'),to_char(c.ask_low,'FM999999999990.000000'),
                    to_char(c.ask_close,'FM999999999990.000000'))),
                    '' ORDER BY i.code,c.granularity,c.timestamp),''),'UTF8'),'sha256'),'hex')
            INTO expected_candle_keys,expected_candle_payloads FROM market_candle c
            JOIN market_instrument i ON i.id=c.instrument_id
            WHERE c.dataset_version_id=reg.dataset_version_id;
          configuration := jsonb_build_object(
            'identity','failed-break-provider-observed-dataset-registration-v1',
            'plan_sha256',plan.sha256,'dataset_manifest_sha256',dataset.manifest_sha256,
            'price_component','COMBINED_BID_ASK',
            'logical_chunk_set_hash',reg.logical_chunk_set_hash,
            'data_contract_sha256',contract.sha256,
            'global_semantic_inventory_sha256',reg.global_semantic_inventory_sha256);
          report := jsonb_build_object('configuration_sha256',reg.configuration_sha256,
            'series_manifest',reg.series_manifest,'row_counts',reg.row_counts,
            'first_last_timestamps',reg.first_last_timestamps,'missingness',reg.missingness,
            'conflict_count',reg.conflict_count,'incident_count',reg.incident_count,
            'logical_chunk_set_hash',reg.logical_chunk_set_hash,
            'successful_attempt_set_hash',reg.successful_attempt_set_hash,
            'ingestion_manifest_set_hash',reg.ingestion_manifest_set_hash,
            'candle_key_hash',reg.candle_key_hash,'candle_payload_hash',reg.candle_payload_hash);
          SELECT coalesce(sum(c.expected_observation_count),0) INTO total_expected
            FROM market_historicalingestionchunk c
            WHERE c.plan_id=reg.plan_id AND c.dataset_version_id=reg.dataset_version_id;
          SELECT count(*) INTO total_candles FROM market_candle
            WHERE dataset_version_id=reg.dataset_version_id;
          IF reg.data_contract_id IS DISTINCT FROM plan.data_contract_id
             OR reg.global_semantic_inventory_sha256
                IS DISTINCT FROM contract.global_semantic_inventory_sha256
             OR dataset.data_contract_sha256 IS DISTINCT FROM contract.sha256
             OR dataset.manifest_sha256<>market_sha256(dataset.manifest)
             OR dataset.manifest->>'historical_plan_sha256' IS DISTINCT FROM plan.sha256
             OR dataset.manifest->>'historical_data_contract_sha256'
                IS DISTINCT FROM contract.sha256
             OR dataset.manifest->>'global_semantic_inventory_sha256'
                IS DISTINCT FROM contract.global_semantic_inventory_sha256
             OR reg.logical_chunk_set_hash<>expected_logical
             OR reg.successful_attempt_set_hash<>expected_attempt
             OR reg.ingestion_manifest_set_hash<>expected_manifest_hash
             OR reg.series_manifest<>expected_series
             OR reg.candle_key_hash<>expected_candle_keys
             OR reg.candle_payload_hash<>expected_candle_payloads
             OR reg.configuration_sha256<>market_sha256(configuration)
             OR reg.report_sha256<>market_sha256(report)
             OR reg.conflict_count<>0 OR reg.incident_count<>0
             OR (SELECT count(*) FROM jsonb_object_keys(reg.row_counts))<>18
             OR (SELECT count(*) FROM jsonb_object_keys(reg.first_last_timestamps))<>18
             OR (SELECT count(*) FROM jsonb_object_keys(reg.missingness))<>18
             OR total_candles<>total_expected
             OR EXISTS (SELECT 1 FROM market_ingestionrun r
                  WHERE r.dataset_version_id=reg.dataset_version_id
                    AND (r.status='running' OR NOT EXISTS
                      (SELECT 1 FROM market_historicalingestionattempt a
                       WHERE a.ingestion_run_id=r.id)))
             OR EXISTS (SELECT 1 FROM market_historicalingestionchunk c
                  WHERE c.plan_id=reg.plan_id
                    AND c.dataset_version_id=reg.dataset_version_id AND
                  (SELECT count(*) FROM market_historicalingestionattempt a
                   JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
                   JOIN market_ingestionmanifest m ON m.ingestion_run_id=r.id
                   WHERE a.chunk_id=c.id AND r.status='succeeded')<>1)
             OR EXISTS (SELECT 1 FROM market_candleconflict
                  WHERE dataset_version_id=reg.dataset_version_id)
             OR EXISTS (SELECT 1 FROM market_dataqualityincident
                  WHERE dataset_version_id=reg.dataset_version_id)
             OR EXISTS (SELECT 1 FROM market_candle c
                  JOIN market_ingestionrun r ON r.id=c.ingestion_run_id
                  LEFT JOIN market_ingestionmanifest m ON m.ingestion_run_id=r.id
                  LEFT JOIN market_historicalingestionattempt a ON a.ingestion_run_id=r.id
                  LEFT JOIN market_historicalingestionchunk h ON h.id=a.chunk_id
                  WHERE c.dataset_version_id=reg.dataset_version_id AND (r.status<>'succeeded'
                    OR r.dataset_version_id<>reg.dataset_version_id
                    OR m.dataset_version_id<>reg.dataset_version_id
                    OR h.dataset_version_id<>reg.dataset_version_id
                    OR h.instrument_id<>c.instrument_id
                    OR h.granularity<>c.granularity OR c.timestamp<h.requested_from
                    OR c.timestamp>=h.requested_to))
          THEN RAISE EXCEPTION
            'replacement dataset is not eligible for exact immutable registration'; END IF;
          SELECT count(*) INTO bad_chunks
            FROM market_historicalingestionchunk c
            JOIN market_historicaltimestampinventory i ON i.id=c.discovery_inventory_id
            LEFT JOIN LATERAL (
              SELECT r.id AS run_id, r.fetched_count, r.stored_count
                FROM market_historicalingestionattempt a
                JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
                 AND r.status='succeeded'
                WHERE a.chunk_id=c.id LIMIT 1) success ON true
            LEFT JOIN LATERAL (
              SELECT count(*) AS n,
                     market_sha256(coalesce(jsonb_agg(
                       market_discovery_timestamp(cd.timestamp)
                       ORDER BY cd.timestamp),'[]')) AS ts_hash
                FROM market_candle cd WHERE cd.ingestion_run_id=success.run_id) candles
              ON true
            WHERE c.plan_id=reg.plan_id AND c.dataset_version_id=reg.dataset_version_id
              AND (success.run_id IS NULL
                OR success.fetched_count<>i.observation_count
                OR success.stored_count<>i.observation_count
                OR candles.n<>i.observation_count
                OR candles.ts_hash<>i.timestamp_set_sha256);
          IF bad_chunks<>0 THEN RAISE EXCEPTION
            'replacement candles do not equal the sealed inventory'; END IF;
          SELECT count(*) INTO bad_series FROM (
            SELECT ins.code AS icode, granularities.granularity AS gran, ins.id AS iid
            FROM market_instrument ins
            JOIN jsonb_array_elements_text(plan.instruments) plan_instruments(code)
              ON plan_instruments.code=ins.code
            CROSS JOIN jsonb_array_elements_text(plan.granularities)
              granularities(granularity)) series
            WHERE (SELECT coalesce(sum(c.expected_observation_count),0)
                   FROM market_historicalingestionchunk c
                   WHERE c.plan_id=reg.plan_id
                     AND c.dataset_version_id=reg.dataset_version_id
                     AND c.instrument_id=series.iid AND c.granularity=series.gran)
                  <>(SELECT count(*) FROM market_candle cd
                     WHERE cd.dataset_version_id=reg.dataset_version_id
                       AND cd.instrument_id=series.iid AND cd.granularity=series.gran)
               OR (reg.row_counts->>(series.icode||':'||series.gran))::integer
                  <>(SELECT count(*) FROM market_candle cd
                     WHERE cd.dataset_version_id=reg.dataset_version_id
                       AND cd.instrument_id=series.iid AND cd.granularity=series.gran)
               OR (reg.missingness->>(series.icode||':'||series.gran))::integer<>0
               OR (reg.first_last_timestamps->(series.icode||':'||series.gran)->>'first')::timestamptz
                  IS DISTINCT FROM (SELECT min(cd.timestamp) FROM market_candle cd
                     WHERE cd.dataset_version_id=reg.dataset_version_id
                       AND cd.instrument_id=series.iid AND cd.granularity=series.gran)
               OR (reg.first_last_timestamps->(series.icode||':'||series.gran)->>'last')::timestamptz
                  IS DISTINCT FROM (SELECT max(cd.timestamp) FROM market_candle cd
                     WHERE cd.dataset_version_id=reg.dataset_version_id
                       AND cd.instrument_id=series.iid AND cd.granularity=series.gran);
          IF bad_series<>0 THEN RAISE EXCEPTION
            'replacement series do not reconstruct the sealed inventory'; END IF;
        END"""


def _contract_governance():
    return import_module("market.migrations.0019_provider_observed_data_contract")


def _governance():
    return import_module("market.migrations.0014_historical_discovery_supersession")


def _execute(schema_editor, statement):
    # psycopg parses % as a placeholder even with no params; escape literal
    # percent signs so restored verbatim bodies keep single % once stored.
    schema_editor.execute(statement.replace("%", "%%"))


def _provider_observed_registration_exists(cursor):
    """Legacy v1 registrations carry no contract lineage and are never counted
    as provider-observed registration evidence."""
    cursor.execute(
        """SELECT count(*) FROM market_datasetregistration r
           JOIN market_historicaldatasetplan p ON p.id=r.plan_id
           WHERE r.data_contract_id IS NOT NULL
              OR r.global_semantic_inventory_sha256 IS NOT NULL
              OR p.data_contract_id IS NOT NULL"""
    )
    return cursor.fetchone()[0] != 0


def preflight_registration_validator(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    governance = _governance()
    contract_governance = _contract_governance()
    problems = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0021_FUNCTIONS)])
        found_functions = {}
        for name, identity_arguments, fingerprint in cursor.fetchall():
            found_functions.setdefault(name, []).append((identity_arguments, fingerprint))
        for name, expected in sorted(REQUIRED_0021_FUNCTIONS.items()):
            candidates = found_functions.get(name, [])
            if not candidates:
                problems.append(f"required 0021 function {name} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0021 function {name} has ambiguous overloads")
            elif candidates[0] != tuple(expected):
                problems.append(f"required 0021 function {name} does not match its 0021 definition")
        cursor.execute(
            """SELECT p.proname FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = current_schema() AND p.proname LIKE 'market\\_%'"""
        )
        for (name,) in cursor.fetchall():
            if name not in REQUIRED_0021_FUNCTIONS:
                problems.append(f"unexpected function {name} outside the 0021 catalog")
        cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
        found_triggers = {}
        for table, name, fingerprint in cursor.fetchall():
            found_triggers.setdefault((table, name), []).append(fingerprint)
        for (table, name), expected in sorted(REQUIRED_0021_TRIGGERS.items()):
            candidates = found_triggers.get((table, name), [])
            if not candidates:
                problems.append(f"required 0021 trigger {name} on {table} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0021 trigger {name} on {table} is ambiguous")
            elif candidates[0] != expected:
                problems.append(
                    f"required 0021 trigger {name} on {table} does not match its 0021 definition"
                )
        for table, name in sorted(found_triggers):
            if table.startswith("market_") and (table, name) not in REQUIRED_0021_TRIGGERS:
                problems.append(f"unexpected trigger {name} on {table} outside the 0021 catalog")
        cursor.execute(
            """SELECT prosrc FROM pg_proc
               WHERE proname='market_validate_replacement_registration'"""
        )
        installed = [row[0] for row in cursor.fetchall()]
        if installed != [contract_governance.REPLACEMENT_REGISTRATION_PROSRC]:
            if installed == [CORRECTED_REPLACEMENT_REGISTRATION_PROSRC]:
                problems.append("the corrected registration validator is already installed")
            else:
                problems.append(
                    "installed registration validator does not match its 0019 definition"
                )
        if _provider_observed_registration_exists(cursor):
            problems.append("a provider-observed dataset registration already exists")
    if problems:
        raise RuntimeError(
            "migration 0022 preflight rejected the current catalog: " + "; ".join(problems)
        )


def install_corrected_validator(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_replacement_registration("
        "reg market_datasetregistration) RETURNS void AS $governed$"
        + CORRECTED_REPLACEMENT_REGISTRATION_PROSRC
        + "$governed$ LANGUAGE plpgsql;",
    )


def restore_0019_validator(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        if _provider_observed_registration_exists(cursor):
            raise RuntimeError("provider-observed registration evidence prohibits gate7c reversal")
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_replacement_registration("
        "reg market_datasetregistration) RETURNS void AS $governed$"
        + _contract_governance().REPLACEMENT_REGISTRATION_PROSRC
        + "$governed$ LANGUAGE plpgsql;",
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("market", "0021_provider_observed_full_acquisition_activation"),
    ]

    operations = [
        migrations.RunPython(preflight_registration_validator, migrations.RunPython.noop),
        migrations.RunPython(install_corrected_validator, restore_0019_validator),
    ]
