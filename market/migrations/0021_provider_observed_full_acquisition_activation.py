"""Gate 7B: bounded full replacement acquisition activation.

Additive activation boundary scaling the reviewed Gate 7A pipeline from
the single completed canary to attempt 1 of each of the exact remaining
131 replacement chunks. PostgreSQL independently reconstructs the
accepted canary success before any remaining chunk may start, permits
one attempt per chunk with one globally running replacement acquisition,
permanently closes the completed canary, and enforces acquisition
audit-evidence cardinality. The Gate 7A definitions are restored
byte-identically by an empty reversal."""

from importlib import import_module

from django.db import migrations

# Full portable fingerprints of the complete governed catalog after
# migration 0020, captured from a catalog migrated exactly through 0020
# with the same fingerprint queries migration 0014's preflight uses.
REQUIRED_0020_FUNCTIONS = {
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
    "market_expected_count": (
        "range_start timestamp with time zone, range_end timestamp with time zone, granularity text",
        "e8bf2ac0ea45070f390dfe1e5da1bd00",
    ),
    "market_governed_candle_reject_mutation": ("", "d438297bd8514cd29705680cd1d5548c"),
    "market_historical_evidence_insert": ("", "546539000a130eb85f1f6d0cf78cea23"),
    "market_historical_manifest_insert": ("", "5fadb1fa2a72608e95cd352866ab498f"),
    "market_historical_manifest_valid": (
        "manifest_payload jsonb, manifest_dataset_id bigint, manifest_run_id bigint",
        "ce028f93f90e82c80b7f3f174736adba",
    ),
    "market_ingestion_run_enforce": ("", "f5095175fb5ef11ffb0e4cc386cc0c1c"),
    "market_ingestionmanifest_reject_mutation": ("", "4255aa76032f767b34a92f3554bccf2d"),
    "market_phase2b_immutable": ("", "c26120d5ca143105a00bb9f243b3c00f"),
    "market_registered_completion": (
        "value timestamp with time zone, granularity text",
        "86e7b5a82ff427a64befc27116ea413b",
    ),
    "market_reject_audit_mutation": ("", "d424fbd8975349adca4951faf9822929"),
    "market_reject_superseded_discovery_write": ("", "add43463f7c47323fb9cb8fc3945a26e"),
    "market_sha256": ("value jsonb", "96fd2a64d0e7a49328292c13b3708d98"),
    "market_validate_acquisition_canary": (
        "attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, new_run_id bigint",
        "3115da9e70d44401e3dca8a70a92ce8d",
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
}
REQUIRED_0020_TRIGGERS = {
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
CANARY_LOGICAL_KEY = "e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c"
VERIFY_CANARY_SUCCESS_PROSRC = r"""
        DECLARE chunk record; attempt record; run record; manifest record;
                attempt_count bigint; manifest_count bigint; candle_count bigint;
                matched_count bigint; observation_count bigint; bad_prices bigint;
                key_stream text; payload_stream text; evidence record;
                evidence_count bigint; run_event_count bigint;
        BEGIN
          SELECT c.* INTO chunk FROM market_historicalingestionchunk c
            WHERE c.logical_key='e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c';
          IF chunk.id IS NULL THEN
            RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT count(*) INTO attempt_count FROM market_historicalingestionattempt
            WHERE chunk_id=chunk.id;
          IF attempt_count<>1 THEN
            RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT a.* INTO STRICT attempt FROM market_historicalingestionattempt a
            WHERE a.chunk_id=chunk.id;
          SELECT r.* INTO STRICT run FROM market_ingestionrun r
            WHERE r.id=attempt.ingestion_run_id;
          SELECT count(*) INTO manifest_count FROM market_ingestionmanifest
            WHERE ingestion_run_id=run.id;
          IF attempt.attempt_number<>1
             OR attempt.idempotency_key<>'failed-break-ingestion-attempt:'
                ||'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c:1'
             OR run.status<>'succeeded' OR run.fetched_count<>2932
             OR run.stored_count<>2932 OR run.rejected_count<>0
             OR run.finished_at IS NULL OR manifest_count<>1
          THEN RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT m.* INTO STRICT manifest FROM market_ingestionmanifest m
            WHERE m.ingestion_run_id=run.id;
          SELECT count(*) INTO evidence_count FROM market_auditevent e
            WHERE e.event_type='market.replacement_canary_succeeded'
              AND e.subject_type='HistoricalIngestionAttempt'
              AND e.subject_id=attempt.id::text;
          IF evidence_count<>1 THEN
            RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT e.* INTO STRICT evidence FROM market_auditevent e
            WHERE e.event_type='market.replacement_canary_succeeded'
              AND e.subject_type='HistoricalIngestionAttempt'
              AND e.subject_id=attempt.id::text;
          IF market_sha256(manifest.payload)<>manifest.sha256
             OR evidence.payload->>'ingestion_manifest_sha256' IS DISTINCT FROM manifest.sha256
          THEN RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT count(*) INTO candle_count FROM market_candle cd
            WHERE cd.ingestion_run_id=run.id
              AND cd.dataset_version_id=chunk.dataset_version_id;
          SELECT count(*) INTO observation_count
            FROM market_historicaltimestampobservation o
            WHERE o.inventory_id=chunk.discovery_inventory_id;
          SELECT count(*) INTO matched_count FROM market_candle cd
            JOIN market_historicaltimestampobservation o
              ON o.inventory_id=chunk.discovery_inventory_id
             AND o.timestamp=cd.timestamp AND o.volume=cd.volume
             AND o.complete=cd.complete AND o.bid_present AND o.ask_present
            WHERE cd.ingestion_run_id=run.id
              AND cd.dataset_version_id=chunk.dataset_version_id;
          SELECT count(*) INTO bad_prices FROM market_candle cd
            WHERE cd.ingestion_run_id=run.id
              AND cd.dataset_version_id=chunk.dataset_version_id
              AND (NOT (cd.bid_open > 0 AND cd.bid_open < 1000000)
                OR NOT (cd.bid_high > 0 AND cd.bid_high < 1000000)
                OR NOT (cd.bid_low > 0 AND cd.bid_low < 1000000)
                OR NOT (cd.bid_close > 0 AND cd.bid_close < 1000000)
                OR NOT (cd.ask_open > 0 AND cd.ask_open < 1000000)
                OR NOT (cd.ask_high > 0 AND cd.ask_high < 1000000)
                OR NOT (cd.ask_low > 0 AND cd.ask_low < 1000000)
                OR NOT (cd.ask_close > 0 AND cd.ask_close < 1000000)
                OR cd.bid_low > least(cd.bid_open, cd.bid_close)
                OR cd.bid_high < greatest(cd.bid_open, cd.bid_close)
                OR cd.bid_low > cd.bid_high
                OR cd.ask_low > least(cd.ask_open, cd.ask_close)
                OR cd.ask_high < greatest(cd.ask_open, cd.ask_close)
                OR cd.ask_low > cd.ask_high
                OR cd.bid_open > cd.ask_open OR cd.bid_high > cd.ask_high
                OR cd.bid_low > cd.ask_low OR cd.bid_close > cd.ask_close
                OR NOT cd.complete);
          IF candle_count<>2932 OR observation_count<>2932
             OR matched_count<>2932 OR bad_prices<>0
          THEN RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT string_agg(fragment.key_json, '' ORDER BY fragment.ts),
                 string_agg(fragment.payload_json, '' ORDER BY fragment.ts)
            INTO key_stream, payload_stream
            FROM (
              SELECT cd.timestamp AS ts,
                '["'||i.code||'","'||cd.granularity||'","'
                  ||to_char(cd.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
                  ||'+00:00"]' AS key_json,
                '["'||i.code||'","'||cd.granularity||'","'
                  ||to_char(cd.timestamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
                  ||'+00:00",'||CASE WHEN cd.complete THEN 'true' ELSE 'false' END
                  ||','||cd.volume
                  ||',"'||to_char(cd.bid_open,'FM999999990.000000')
                  ||'","'||to_char(cd.bid_high,'FM999999990.000000')
                  ||'","'||to_char(cd.bid_low,'FM999999990.000000')
                  ||'","'||to_char(cd.bid_close,'FM999999990.000000')
                  ||'","'||to_char(cd.ask_open,'FM999999990.000000')
                  ||'","'||to_char(cd.ask_high,'FM999999990.000000')
                  ||'","'||to_char(cd.ask_low,'FM999999990.000000')
                  ||'","'||to_char(cd.ask_close,'FM999999990.000000')||'"]' AS payload_json
              FROM market_candle cd
              JOIN market_instrument i ON i.id=cd.instrument_id
              WHERE cd.ingestion_run_id=run.id
                AND cd.dataset_version_id=chunk.dataset_version_id
            ) AS fragment;
          IF encode(digest(convert_to(key_stream,'UTF8'),'sha256'),'hex')
               IS DISTINCT FROM evidence.payload->>'candle_key_hash'
             OR encode(digest(convert_to(payload_stream,'UTF8'),'sha256'),'hex')
               IS DISTINCT FROM evidence.payload->>'candle_payload_hash'
          THEN RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          IF market_sha256(evidence.payload - 'schema_version' - 'provider_evidence'
                           - 'terminal_event_sha256' - 'operational_evidence_sha256')
               IS DISTINCT FROM evidence.payload->>'terminal_event_sha256'
             OR market_sha256(jsonb_build_array(
                  evidence.payload->'terminal_event_sha256',
                  evidence.payload->'provider_evidence',
                  to_jsonb(attempt.idempotency_key)))
               IS DISTINCT FROM evidence.payload->>'operational_evidence_sha256'
             OR evidence.payload->>'logical_key'<>chunk.logical_key
             OR (evidence.payload->>'stored_candle_count')::bigint<>2932
          THEN RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
          SELECT count(*) INTO run_event_count FROM market_auditevent e
            WHERE e.event_type='market.ingestion_succeeded'
              AND e.subject_type='IngestionRun' AND e.subject_id=run.id::text;
          IF run_event_count<>1
             OR EXISTS (SELECT 1 FROM market_auditevent e
                  WHERE e.event_type='market.historical_ingestion_failed'
                    AND e.subject_type='HistoricalIngestionAttempt'
                    AND e.subject_id=attempt.id::text)
             OR EXISTS (SELECT 1 FROM market_datasetregistration)
          THEN RAISE EXCEPTION 'replacement canary success does not reconstruct'; END IF;
        END """
ACQUISITION_GATE7B_PROSRC = r"""
        DECLARE chunk record; plan record; contract record; dataset record;
                registration record; approval record; inventory record;
                discovery_chunk record; observation_rows bigint; chunk_total bigint;
                expected_key text;
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended('gate7b-replacement-acquisition',0));
          SELECT * INTO STRICT chunk FROM market_historicalingestionchunk
            WHERE id=attempt_chunk_id;
          SELECT * INTO STRICT plan FROM market_historicaldatasetplan WHERE id=chunk.plan_id;
          IF plan.data_contract_id IS NULL THEN
            RAISE EXCEPTION 'replacement acquisition activation rejects this attempt';
          END IF;
          SELECT * INTO STRICT contract FROM market_historicaldatacontract
            WHERE id=plan.data_contract_id;
          SELECT * INTO STRICT dataset FROM market_datasetversion
            WHERE id=chunk.dataset_version_id;
          SELECT r.*, p.sha256 AS discovery_plan_sha256, p.sealed_at AS plan_sealed_at
            INTO STRICT registration
            FROM market_historicaldiscoveryregistration r
            JOIN market_historicaldiscoveryplan p ON p.id=r.plan_id
            WHERE r.id=contract.discovery_registration_id;
          SELECT * INTO STRICT approval FROM market_historicaldiscoveryapproval
            WHERE id=registration.approval_id;
          SELECT * INTO STRICT inventory FROM market_historicaltimestampinventory
            WHERE id=chunk.discovery_inventory_id;
          SELECT * INTO STRICT discovery_chunk FROM market_historicaldiscoverychunk
            WHERE id=inventory.chunk_id;
          SELECT count(*) INTO observation_rows FROM market_historicaltimestampobservation
            WHERE inventory_id=inventory.id;
          SELECT count(*) INTO chunk_total FROM market_historicalingestionchunk c
            WHERE c.plan_id=plan.id;
          expected_key := market_sha256(jsonb_build_object(
            'canonical_request_sha256',chunk.canonical_request_sha256,
            'replacement_dataset_manifest_sha256',dataset.manifest_sha256,
            'replacement_plan_sha256',plan.sha256,
            'semantic_inventory_sha256',chunk.semantic_inventory_sha256));
          IF contract.sha256<>'60b603f26662bfc8faa4373177690bc0ae23820b914815f47c11d8367c07f7bf'
             OR market_sha256(contract.payload)<>contract.sha256
             OR contract.identity<>'oanda-ba-ny17-friday-provider-observed-v1'
             OR contract.global_semantic_inventory_sha256<>
                '78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c'
             OR contract.approval_sha256<>
                '41d3d0cc97c82882fd56fd1459b71df862f76d2e4c698eb759df1a82a0f25586'
             OR contract.approval_sha256<>approval.sha256
             OR contract.registration_report_sha256<>
                'cd0acdcb52aa0a321aed3ecbb4a7f9edc38fa8d31444c5bbc2927fefd9154844'
             OR contract.registration_report_sha256<>registration.report_sha256
             OR registration.plan_sealed_at IS NULL
             OR registration.plan_sealed_at<>registration.registered_at
             OR registration.discovery_plan_sha256<>
                '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
             OR registration.ordered_chunk_manifest_sha256<>
                '04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR registration.global_semantic_inventory_sha256<>
                contract.global_semantic_inventory_sha256
             OR plan.sha256<>'f0be516c732d775ce57fd98a39a7dd7df917d4eaa2c9c0ffd2fc7028d9a23528'
             OR market_sha256(plan.payload)<>plan.sha256
             OR plan.data_contract_sha256<>contract.sha256
             OR dataset.manifest_sha256<>
                '9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54'
             OR market_sha256(dataset.manifest)<>dataset.manifest_sha256
             OR dataset.data_contract_sha256<>contract.sha256
             OR chunk_total<>132
             OR chunk.data_contract_sha256<>contract.sha256
             OR chunk.logical_key<>expected_key
             OR inventory.semantic_inventory_sha256<>chunk.semantic_inventory_sha256
             OR inventory.observation_count<>chunk.expected_observation_count
             OR observation_rows<>chunk.expected_observation_count
             OR chunk.expected_observation_count NOT BETWEEN 1 AND 4999
             OR discovery_chunk.canonical_request_sha256<>chunk.canonical_request_sha256
             OR discovery_chunk.requested_from<>chunk.requested_from
             OR discovery_chunk.requested_to<>chunk.requested_to
             OR new_attempt_number<>1
             OR new_idempotency_key<>'failed-break-ingestion-attempt:'
                ||chunk.logical_key||':1'
             OR EXISTS (SELECT 1 FROM market_historicalingestionattempt a
                        WHERE a.chunk_id=chunk.id)
             OR EXISTS (SELECT 1 FROM market_ingestionrun r2
                        JOIN market_historicalingestionattempt a2
                          ON a2.ingestion_run_id=r2.id
                        JOIN market_historicalingestionchunk c2 ON c2.id=a2.chunk_id
                        WHERE c2.data_contract_sha256 IS NOT NULL
                          AND r2.status='running' AND r2.id<>new_run_id)
             OR EXISTS (SELECT 1 FROM market_datasetregistration
                        WHERE dataset_version_id=chunk.dataset_version_id)
          THEN RAISE EXCEPTION
            'replacement acquisition activation rejects this attempt'; END IF;
          IF chunk.logical_key<>
             'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c' THEN
            PERFORM market_verify_replacement_canary_success();
          END IF;
        END """
INGESTION_RUN_GATE7B_PROSRC = r"""
        DECLARE historical boolean; has_attempt boolean;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            historical := NEW.dataset_version_id IS NOT NULL AND EXISTS
              (SELECT 1 FROM market_datasetversion WHERE id=NEW.dataset_version_id
               AND manifest ? 'historical_plan_sha256');
            IF historical AND (EXISTS (SELECT 1 FROM market_datasetregistration
                 WHERE dataset_version_id=NEW.dataset_version_id)
              OR NOT EXISTS (SELECT 1 FROM market_historicalingestionchunk c
                 JOIN market_historicaldatasetplan p ON p.id=c.plan_id
                 WHERE c.dataset_version_id=NEW.dataset_version_id AND p.source_id=NEW.source_id
                 AND c.instrument_id=NEW.instrument_id AND c.granularity=NEW.granularity
                 AND c.requested_from=NEW.requested_from AND c.requested_to=NEW.requested_to
                 AND c.canonical_request=NEW.parameters))
            THEN RAISE EXCEPTION 'historical run lacks open canonical chunk lineage'; END IF;
            IF NEW.dataset_version_id IS NOT NULL AND EXISTS (
                 SELECT 1 FROM market_datasetversion dv
                 WHERE dv.id=NEW.dataset_version_id
                   AND dv.data_contract_sha256 IS NOT NULL) THEN
              IF NOT EXISTS (SELECT 1 FROM market_historicalingestionchunk cc
                    WHERE cc.dataset_version_id=NEW.dataset_version_id
                      AND cc.data_contract_sha256 IS NOT NULL
                      AND cc.instrument_id=NEW.instrument_id
                      AND cc.granularity=NEW.granularity
                      AND cc.requested_from=NEW.requested_from
                      AND cc.requested_to=NEW.requested_to
                      AND cc.canonical_request=NEW.parameters
                      AND NOT EXISTS (SELECT 1 FROM market_historicalingestionattempt pa
                                      WHERE pa.chunk_id=cc.id))
                 OR EXISTS (SELECT 1 FROM market_ingestionrun rr
                      JOIN market_datasetversion dv2 ON dv2.id=rr.dataset_version_id
                      WHERE dv2.data_contract_sha256 IS NOT NULL
                        AND rr.status='running')
              THEN RAISE EXCEPTION
                'replacement acquisition activation rejects this ingestion run'; END IF;
            END IF;
            RETURN NEW;
          END IF;
          has_attempt := EXISTS (SELECT 1 FROM market_historicalingestionattempt
                                  WHERE ingestion_run_id=OLD.id);
          IF TG_OP='DELETE' THEN
            IF OLD.status <> 'running' OR has_attempt THEN
              RAISE EXCEPTION 'ingestion runs with audit lineage cannot be deleted';
            END IF; RETURN OLD;
          END IF;
          IF NEW.status='quarantined' AND EXISTS (
               SELECT 1 FROM market_historicalingestionattempt a
               JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
               JOIN market_datasetversion d ON d.id=c.dataset_version_id
               JOIN market_historicaldatasetplan p ON p.id=c.plan_id
               JOIN market_historicaldatacontract hc ON hc.id=p.data_contract_id
               WHERE a.ingestion_run_id=NEW.id
                 AND c.data_contract_sha256 IS NOT NULL
                 AND d.data_contract_sha256=c.data_contract_sha256
                 AND p.data_contract_sha256=c.data_contract_sha256
                 AND hc.sha256=c.data_contract_sha256)
          THEN RAISE EXCEPTION
            'replacement acquisition runs may not be quarantined'; END IF;
          IF OLD.status <> 'running' OR NEW.status NOT IN ('succeeded','failed','quarantined')
             OR NEW.finished_at IS NULL OR NEW.source_id<>OLD.source_id
             OR NEW.dataset_version_id IS DISTINCT FROM OLD.dataset_version_id
             OR NEW.instrument_id<>OLD.instrument_id OR NEW.granularity<>OLD.granularity
             OR NEW.requested_from<>OLD.requested_from OR NEW.requested_to<>OLD.requested_to
             OR NEW.parameters IS DISTINCT FROM OLD.parameters
             OR NEW.request_manifest_hash<>OLD.request_manifest_hash OR NEW.started_at<>OLD.started_at
             OR (NEW.status='succeeded' AND has_attempt AND NOT EXISTS
                 (SELECT 1 FROM market_ingestionmanifest WHERE ingestion_run_id=NEW.id))
          THEN RAISE EXCEPTION 'ingestion run may make one valid terminal transition only'; END IF;
          RETURN NEW;
        END """
# Commit-time audit-evidence existence: a governed replacement-acquisition
# run may only become terminal together with exactly its two-scope evidence.
# Scoped relationally (run -> historical attempt -> chunk/dataset contract
# lineage), inert for v1 acquisition, discovery and prospective ingestion;
# installed only while Gate 7B activation is present.
AUDIT_COMPLETENESS_PROSRC = r"""
        DECLARE attempt record; chunk record; dataset record; manifest record;
                run_event record; evidence record;
                run_succeeded bigint; run_rejected bigint;
                attempt_success bigint; attempt_failure bigint;
        BEGIN
          IF OLD.status <> 'running' OR NEW.status NOT IN ('succeeded','failed') THEN
            RETURN NULL; END IF;
          SELECT a.* INTO attempt FROM market_historicalingestionattempt a
            WHERE a.ingestion_run_id=NEW.id;
          IF attempt.id IS NULL THEN RETURN NULL; END IF;
          SELECT c.* INTO STRICT chunk FROM market_historicalingestionchunk c
            WHERE c.id=attempt.chunk_id;
          IF chunk.data_contract_sha256 IS NULL THEN RETURN NULL; END IF;
          SELECT d.* INTO STRICT dataset FROM market_datasetversion d
            WHERE d.id=chunk.dataset_version_id;
          IF dataset.data_contract_sha256 IS NULL
             OR dataset.data_contract_sha256<>chunk.data_contract_sha256 THEN
            RETURN NULL; END IF;
          SELECT count(*) INTO run_succeeded FROM market_auditevent e
            WHERE e.subject_type='IngestionRun' AND e.subject_id=NEW.id::text
              AND e.event_type='market.ingestion_succeeded';
          SELECT count(*) INTO run_rejected FROM market_auditevent e
            WHERE e.subject_type='IngestionRun' AND e.subject_id=NEW.id::text
              AND e.event_type='market.ingestion_rejected';
          SELECT count(*) INTO attempt_success FROM market_auditevent e
            WHERE e.subject_type='HistoricalIngestionAttempt'
              AND e.subject_id=attempt.id::text
              AND e.event_type IN ('market.replacement_canary_succeeded',
                                   'market.replacement_acquisition_succeeded');
          SELECT count(*) INTO attempt_failure FROM market_auditevent e
            WHERE e.subject_type='HistoricalIngestionAttempt'
              AND e.subject_id=attempt.id::text
              AND e.event_type='market.historical_ingestion_failed';
          IF NEW.status='succeeded' THEN
            IF run_succeeded<>1 OR run_rejected<>0
               OR attempt_success<>1 OR attempt_failure<>0
            THEN RAISE EXCEPTION
              'replacement acquisition terminal commit requires its audit evidence';
            END IF;
            SELECT m.* INTO manifest FROM market_ingestionmanifest m
              WHERE m.ingestion_run_id=NEW.id;
            SELECT e.* INTO STRICT run_event FROM market_auditevent e
              WHERE e.subject_type='IngestionRun' AND e.subject_id=NEW.id::text
                AND e.event_type='market.ingestion_succeeded';
            SELECT e.* INTO STRICT evidence FROM market_auditevent e
              WHERE e.subject_type='HistoricalIngestionAttempt'
                AND e.subject_id=attempt.id::text
                AND e.event_type IN ('market.replacement_canary_succeeded',
                                     'market.replacement_acquisition_succeeded');
            IF manifest.id IS NULL
               OR (run_event.payload->>'fetched')::bigint
                  IS DISTINCT FROM NEW.fetched_count
               OR (run_event.payload->>'stored')::bigint
                  IS DISTINCT FROM NEW.stored_count
               OR run_event.payload->>'manifest' IS DISTINCT FROM manifest.sha256
               OR evidence.payload->>'logical_key' IS DISTINCT FROM chunk.logical_key
               OR (evidence.payload->>'attempt_number')::integer
                  IS DISTINCT FROM attempt.attempt_number
               OR evidence.payload->>'ingestion_manifest_sha256'
                  IS DISTINCT FROM manifest.sha256
               OR (evidence.payload->>'stored_candle_count')::bigint
                  IS DISTINCT FROM NEW.stored_count
               OR evidence.payload->>'canonical_request_sha256'
                  IS DISTINCT FROM chunk.canonical_request_sha256
               OR evidence.payload->>'terminal_event_sha256' IS DISTINCT FROM
                  market_sha256(evidence.payload - 'schema_version' - 'provider_evidence'
                                - 'terminal_event_sha256' - 'operational_evidence_sha256')
               OR evidence.payload->>'operational_evidence_sha256' IS DISTINCT FROM
                  market_sha256(jsonb_build_array(
                    evidence.payload->'terminal_event_sha256',
                    evidence.payload->'provider_evidence',
                    to_jsonb(attempt.idempotency_key)))
               OR (evidence.event_type='market.replacement_canary_succeeded'
                   AND chunk.logical_key<>
                'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c')
               OR (evidence.event_type='market.replacement_acquisition_succeeded'
                   AND chunk.logical_key=
                'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c')
            THEN RAISE EXCEPTION
              'replacement acquisition terminal commit requires its audit evidence';
            END IF;
          ELSE
            IF run_rejected<>1 OR run_succeeded<>0
               OR attempt_failure<>1 OR attempt_success<>0
            THEN RAISE EXCEPTION
              'replacement acquisition terminal commit requires its audit evidence';
            END IF;
            SELECT e.* INTO STRICT run_event FROM market_auditevent e
              WHERE e.subject_type='IngestionRun' AND e.subject_id=NEW.id::text
                AND e.event_type='market.ingestion_rejected';
            SELECT e.* INTO STRICT evidence FROM market_auditevent e
              WHERE e.subject_type='HistoricalIngestionAttempt'
                AND e.subject_id=attempt.id::text
                AND e.event_type='market.historical_ingestion_failed';
            IF coalesce(run_event.payload->>'error_code','')=''
               OR coalesce(evidence.payload->>'error_code','')=''
               OR evidence.payload->>'logical_chunk_key'
                  IS DISTINCT FROM chunk.logical_key
            THEN RAISE EXCEPTION
              'replacement acquisition terminal commit requires its audit evidence';
            END IF;
          END IF;
          RETURN NULL;
        END """

# The Gate 7A candle branch without its canary logical-key pin: every
# replacement candle still requires exact sealed-observation equality
# and the full strict price predicates for its own chunk.
GOVERNED_CANDLE_GATE7B_PROSRC = r"""
        DECLARE chunk record;
        BEGIN
          IF TG_OP='DELETE' THEN IF OLD.dataset_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'governed dataset candles are append-only'; END IF; RETURN OLD; END IF;
          IF TG_OP='UPDATE' THEN IF OLD.dataset_version_id IS NOT NULL OR NEW.dataset_version_id IS NOT NULL
            THEN RAISE EXCEPTION 'governed dataset candles must be inserted and are append-only'; END IF;
            RETURN NEW; END IF;
          IF NEW.dataset_version_id IS NULL THEN RETURN NEW; END IF;
          IF EXISTS (SELECT 1 FROM market_datasetregistration WHERE dataset_version_id=NEW.dataset_version_id)
            THEN RAISE EXCEPTION 'registered historical dataset is sealed'; END IF;
          IF EXISTS (SELECT 1 FROM market_datasetversion WHERE id=NEW.dataset_version_id
                     AND manifest ? 'historical_plan_sha256') THEN
            SELECT c.* INTO chunk FROM market_historicalingestionattempt a
              JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
              WHERE a.ingestion_run_id=NEW.ingestion_run_id;
            IF chunk.id IS NOT NULL AND chunk.data_contract_sha256 IS NOT NULL THEN
              IF chunk.dataset_version_id<>NEW.dataset_version_id
                 OR chunk.instrument_id<>NEW.instrument_id
                 OR chunk.granularity<>NEW.granularity
                 OR NOT NEW.complete OR NEW.timestamp<chunk.requested_from
                 OR NEW.timestamp>=chunk.requested_to
                 OR NOT EXISTS (SELECT 1 FROM market_historicaltimestampobservation o
                      WHERE o.inventory_id=chunk.discovery_inventory_id
                        AND o.timestamp=NEW.timestamp AND o.volume=NEW.volume
                        AND o.complete AND o.bid_present AND o.ask_present)
                 OR NOT (NEW.bid_open > 0 AND NEW.bid_open < 1000000)
                 OR NOT (NEW.bid_high > 0 AND NEW.bid_high < 1000000)
                 OR NOT (NEW.bid_low > 0 AND NEW.bid_low < 1000000)
                 OR NOT (NEW.bid_close > 0 AND NEW.bid_close < 1000000)
                 OR NOT (NEW.ask_open > 0 AND NEW.ask_open < 1000000)
                 OR NOT (NEW.ask_high > 0 AND NEW.ask_high < 1000000)
                 OR NOT (NEW.ask_low > 0 AND NEW.ask_low < 1000000)
                 OR NOT (NEW.ask_close > 0 AND NEW.ask_close < 1000000)
                 OR NEW.bid_low > least(NEW.bid_open, NEW.bid_close)
                 OR NEW.bid_high < greatest(NEW.bid_open, NEW.bid_close)
                 OR NEW.bid_low > NEW.bid_high
                 OR NEW.ask_low > least(NEW.ask_open, NEW.ask_close)
                 OR NEW.ask_high < greatest(NEW.ask_open, NEW.ask_close)
                 OR NEW.ask_low > NEW.ask_high
                 OR NEW.bid_open > NEW.ask_open OR NEW.bid_high > NEW.ask_high
                 OR NEW.bid_low > NEW.ask_low OR NEW.bid_close > NEW.ask_close
              THEN RAISE EXCEPTION
                'replacement candle conflicts with the sealed inventory'; END IF;
            ELSE
              IF chunk.id IS NULL OR chunk.dataset_version_id<>NEW.dataset_version_id
               OR chunk.instrument_id<>NEW.instrument_id OR chunk.granularity<>NEW.granularity
               OR NOT NEW.complete OR NEW.timestamp<chunk.requested_from
               OR NEW.timestamp>=chunk.requested_to
               OR market_expected_count(NEW.timestamp,
                    market_registered_completion(NEW.timestamp,NEW.granularity),NEW.granularity)<>1
               OR market_registered_completion(NEW.timestamp,NEW.granularity)
                    >= timestamptz '2019-01-01 05:00:00+00'
            THEN RAISE EXCEPTION 'historical candle conflicts with chunk lineage or boundary'; END IF;
            END IF;
          END IF; RETURN NEW;
        END """
ACQUISITION_AUDIT_PROSRC = r"""
        DECLARE run record; attempt record; chunk record;
        BEGIN
          IF NEW.event_type IN ('market.ingestion_succeeded','market.ingestion_rejected')
             AND NEW.subject_type='IngestionRun' AND NEW.subject_id~'^[1-9][0-9]*$' THEN
            SELECT r.* INTO run FROM market_ingestionrun r
              WHERE r.id=NEW.subject_id::bigint;
            IF run.id IS NOT NULL AND EXISTS (SELECT 1 FROM market_datasetversion dv
                 WHERE dv.id=run.dataset_version_id
                   AND dv.data_contract_sha256 IS NOT NULL) THEN
              PERFORM pg_advisory_xact_lock(hashtextextended(
                'acquisition-audit-run:'||NEW.subject_id,0));
              IF (NEW.event_type='market.ingestion_succeeded' AND run.status<>'succeeded')
                 OR (NEW.event_type='market.ingestion_rejected' AND run.status<>'failed')
                 OR EXISTS (SELECT 1 FROM market_auditevent e
                      WHERE e.subject_type='IngestionRun'
                        AND e.subject_id=NEW.subject_id
                        AND e.event_type IN ('market.ingestion_succeeded',
                                             'market.ingestion_rejected'))
              THEN RAISE EXCEPTION
                'replacement acquisition audit evidence rejected'; END IF;
            END IF;
          END IF;
          IF NEW.event_type IN ('market.replacement_canary_succeeded',
                                'market.replacement_acquisition_succeeded',
                                'market.historical_ingestion_failed')
             AND NEW.subject_type='HistoricalIngestionAttempt'
             AND NEW.subject_id~'^[1-9][0-9]*$' THEN
            SELECT a.* INTO attempt FROM market_historicalingestionattempt a
              WHERE a.id=NEW.subject_id::bigint;
            IF attempt.id IS NOT NULL THEN
              SELECT c.* INTO STRICT chunk FROM market_historicalingestionchunk c
                WHERE c.id=attempt.chunk_id;
              IF chunk.data_contract_sha256 IS NOT NULL THEN
                PERFORM pg_advisory_xact_lock(hashtextextended(
                  'acquisition-audit-attempt:'||NEW.subject_id,0));
                SELECT r.* INTO STRICT run FROM market_ingestionrun r
                  WHERE r.id=attempt.ingestion_run_id;
                IF EXISTS (SELECT 1 FROM market_auditevent e
                     WHERE e.subject_type='HistoricalIngestionAttempt'
                       AND e.subject_id=NEW.subject_id
                       AND e.event_type IN ('market.replacement_canary_succeeded',
                                            'market.replacement_acquisition_succeeded',
                                            'market.historical_ingestion_failed'))
                THEN RAISE EXCEPTION
                  'replacement acquisition audit evidence rejected'; END IF;
                IF NEW.event_type='market.historical_ingestion_failed' THEN
                  IF run.status<>'failed'
                     OR coalesce(NEW.payload->>'error_code','')=''
                     OR NEW.payload->>'logical_chunk_key' IS DISTINCT FROM chunk.logical_key
                  THEN RAISE EXCEPTION
                    'replacement acquisition audit evidence rejected'; END IF;
                ELSE
                  IF run.status<>'succeeded'
                     OR (NEW.event_type='market.replacement_canary_succeeded'
                         AND chunk.logical_key<>
                'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c')
                     OR (NEW.event_type='market.replacement_acquisition_succeeded'
                         AND chunk.logical_key=
                'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c')
                     OR NEW.payload->>'logical_key' IS DISTINCT FROM chunk.logical_key
                     OR NEW.payload->>'terminal_event_sha256' IS DISTINCT FROM
                        market_sha256(NEW.payload - 'schema_version' - 'provider_evidence'
                                      - 'terminal_event_sha256'
                                      - 'operational_evidence_sha256')
                  THEN RAISE EXCEPTION
                    'replacement acquisition audit evidence rejected'; END IF;
                END IF;
              END IF;
            END IF;
          END IF;
          RETURN NEW;
        END """


def _gate7a():
    return import_module("market.migrations.0020_provider_observed_acquisition_canary_activation")


def _governance():
    return import_module("market.migrations.0014_historical_discovery_supersession")


def _execute(schema_editor, statement):
    # psycopg parses % as a placeholder even with no params; escape literal
    # percent signs so restored verbatim bodies keep single % once stored.
    schema_editor.execute(statement.replace("%", "%%"))


def preflight_full_acquisition(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    governance = _governance()
    problems = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0020_FUNCTIONS)])
        found_functions = {}
        for name, identity_arguments, fingerprint in cursor.fetchall():
            found_functions.setdefault(name, []).append((identity_arguments, fingerprint))
        for name, expected in sorted(REQUIRED_0020_FUNCTIONS.items()):
            candidates = found_functions.get(name, [])
            if not candidates:
                problems.append(f"required 0020 function {name} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0020 function {name} has ambiguous overloads")
            elif candidates[0] != tuple(expected):
                problems.append(f"required 0020 function {name} does not match its 0020 definition")
        cursor.execute(
            """SELECT p.proname FROM pg_proc p
               JOIN pg_namespace n ON n.oid = p.pronamespace
               WHERE n.nspname = current_schema() AND p.proname LIKE 'market\\_%'"""
        )
        for (name,) in cursor.fetchall():
            if name not in REQUIRED_0020_FUNCTIONS:
                problems.append(f"unexpected function {name} outside the 0020 catalog")
        cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
        found_triggers = {}
        for table, name, fingerprint in cursor.fetchall():
            found_triggers.setdefault((table, name), []).append(fingerprint)
        for (table, name), expected in sorted(REQUIRED_0020_TRIGGERS.items()):
            candidates = found_triggers.get((table, name), [])
            if not candidates:
                problems.append(f"required 0020 trigger {name} on {table} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0020 trigger {name} on {table} is ambiguous")
            elif candidates[0] != expected:
                problems.append(
                    f"required 0020 trigger {name} on {table} does not match its 0020 definition"
                )
        for table, name in sorted(found_triggers):
            if table.startswith("market_") and (table, name) not in REQUIRED_0020_TRIGGERS:
                problems.append(f"unexpected trigger {name} on {table} outside the 0020 catalog")
        cursor.execute(
            """SELECT count(*) FROM market_historicalingestionattempt a
               JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
               WHERE c.data_contract_sha256 IS NOT NULL AND c.logical_key <> %s""",
            [CANARY_LOGICAL_KEY],
        )
        if cursor.fetchone()[0] != 0:
            problems.append("non-canary replacement acquisition attempts already exist")
        cursor.execute(
            """SELECT count(*) FROM market_auditevent
               WHERE event_type='market.replacement_acquisition_succeeded'"""
        )
        if cursor.fetchone()[0] != 0:
            problems.append("replacement acquisition audit evidence already exists")
    if problems:
        raise RuntimeError(
            "migration 0021 preflight rejected the current catalog: " + "; ".join(problems)
        )


def install_full_acquisition(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _execute(
        schema_editor,
        "CREATE FUNCTION market_verify_replacement_canary_success() "
        "RETURNS void AS $governed$" + VERIFY_CANARY_SUCCESS_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_acquisition_canary("
        "attempt_chunk_id bigint, new_attempt_number integer, "
        "new_idempotency_key text, new_run_id bigint) RETURNS void AS $governed$"
        + ACQUISITION_GATE7B_PROSRC
        + "$governed$ LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_ingestion_run_enforce() "
        "RETURNS trigger AS $governed$" + INGESTION_RUN_GATE7B_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_governed_candle_reject_mutation() "
        "RETURNS trigger AS $governed$" + GOVERNED_CANDLE_GATE7B_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE FUNCTION market_validate_acquisition_audit() "
        "RETURNS trigger AS $governed$" + ACQUISITION_AUDIT_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE TRIGGER market_acquisition_audit_validate BEFORE INSERT "
        "ON market_auditevent FOR EACH ROW "
        "EXECUTE FUNCTION market_validate_acquisition_audit();",
    )
    _execute(
        schema_editor,
        "CREATE FUNCTION market_enforce_acquisition_audit_completeness() "
        "RETURNS trigger AS $governed$" + AUDIT_COMPLETENESS_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE CONSTRAINT TRIGGER market_acquisition_audit_complete "
        "AFTER UPDATE OF status ON market_ingestionrun "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION market_enforce_acquisition_audit_completeness();",
    )


def remove_full_acquisition(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT
                 (SELECT count(*) FROM market_historicalingestionattempt a
                  JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
                  WHERE c.data_contract_sha256 IS NOT NULL AND c.logical_key <> %s)
               + (SELECT count(*) FROM market_auditevent
                  WHERE event_type='market.replacement_acquisition_succeeded')""",
            [CANARY_LOGICAL_KEY],
        )
        if cursor.fetchone()[0] != 0:
            raise RuntimeError("replacement acquisition evidence prohibits gate7b reversal")
    gate7a = _gate7a()
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_acquisition_canary("
        "attempt_chunk_id bigint, new_attempt_number integer, "
        "new_idempotency_key text, new_run_id bigint) RETURNS void AS $governed$"
        + gate7a.ACQUISITION_CANARY_PROSRC
        + "$governed$ LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_ingestion_run_enforce() "
        "RETURNS trigger AS $governed$" + gate7a.INGESTION_RUN_GATE7A_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_governed_candle_reject_mutation() "
        "RETURNS trigger AS $governed$" + gate7a.GOVERNED_CANDLE_GATE7A_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "DROP TRIGGER market_acquisition_audit_complete ON market_ingestionrun;",
    )
    _execute(
        schema_editor,
        "DROP FUNCTION market_enforce_acquisition_audit_completeness();",
    )
    _execute(
        schema_editor,
        "DROP TRIGGER market_acquisition_audit_validate ON market_auditevent;",
    )
    _execute(schema_editor, "DROP FUNCTION market_validate_acquisition_audit();")
    _execute(schema_editor, "DROP FUNCTION market_verify_replacement_canary_success();")


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("market", "0020_provider_observed_acquisition_canary_activation"),
    ]

    operations = [
        migrations.RunPython(preflight_full_acquisition, migrations.RunPython.noop),
        migrations.RunPython(install_full_acquisition, remove_full_acquisition),
    ]
