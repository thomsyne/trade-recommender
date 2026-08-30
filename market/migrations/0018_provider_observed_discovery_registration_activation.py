from importlib import import_module

from django.db import migrations

# Full portable fingerprints of the complete governed catalog this migration
# depends on, captured with the 0014 fingerprint queries from a catalog
# migrated exactly through 0017: every market_* governance function and every
# trigger on the discovery, audit and ingestion tables that protects the
# evidence Gate 5 registration relies upon.
REQUIRED_0017_FUNCTIONS = {
    "market_candleconflict_reject_mutation": (
        "",
        "7f669c1be82b32cdb408b09dae92827f",
    ),
    "market_canonical_json": (
        "value jsonb",
        "aa43ea03a68b240dfcda6e2404c500a6",
    ),
    "market_dataqualityincident_reject_mutation": (
        "",
        "1d58428d31a48e46472419a7fa1c45a5",
    ),
    "market_discovery_audit_reject_mutation": (
        "",
        "d91bbb0f631c2f39f8bcb229e16cd656",
    ),
    "market_discovery_audit_reject_truncate": (
        "",
        "b5b0de2bd49976d91725d85295861ad3",
    ),
    "market_discovery_operational_timestamp": (
        "value timestamp with time zone",
        "0ade13a9b0800de89465ec203f3a6f45",
    ),
    "market_discovery_plan_xact_lock": (
        "plan_key bigint",
        "049915d1c7640a273f7c1946d90c272a",
    ),
    "market_discovery_reject_mutation": (
        "",
        "92d96335c5a444cfdb531c1423310a80",
    ),
    "market_discovery_reject_sealed_insert": (
        "",
        "1c07d17226742eb2e6822f3d37052d47",
    ),
    "market_discovery_reject_truncate": (
        "",
        "967b6921befcaf664b08f7456f5dc27d",
    ),
    "market_discovery_structural_diagnostics_valid": (
        "diagnostics jsonb, fetched integer",
        "4a587767d6def1327aa0f65e2bc6d845",
    ),
    "market_discovery_supersession_reject_mutation": (
        "",
        "ffdd7694b355279f9caf69aa15c00db9",
    ),
    "market_discovery_supersession_reject_truncate": (
        "",
        "e5a8bd59d73d9862ca49fc22828920c1",
    ),
    "market_discovery_timestamp": (
        "value timestamp with time zone",
        "b7dafb1af452f2c208f4b0c2c2ef4dc3",
    ),
    "market_expected_count": (
        "range_start timestamp with time zone, range_end timestamp with time zone, granularity text",
        "e8bf2ac0ea45070f390dfe1e5da1bd00",
    ),
    "market_governed_candle_reject_mutation": (
        "",
        "4164da30f02bc83aa5b7945c5231ffd3",
    ),
    "market_historical_evidence_insert": (
        "",
        "546539000a130eb85f1f6d0cf78cea23",
    ),
    "market_historical_manifest_insert": (
        "",
        "5fadb1fa2a72608e95cd352866ab498f",
    ),
    "market_historical_manifest_valid": (
        "manifest_payload jsonb, manifest_dataset_id bigint, manifest_run_id bigint",
        "ce028f93f90e82c80b7f3f174736adba",
    ),
    "market_ingestion_run_enforce": (
        "",
        "5527e44615986366aeebb6e943918769",
    ),
    "market_ingestionmanifest_reject_mutation": (
        "",
        "4255aa76032f767b34a92f3554bccf2d",
    ),
    "market_phase2b_immutable": (
        "",
        "c26120d5ca143105a00bb9f243b3c00f",
    ),
    "market_registered_completion": (
        "value timestamp with time zone, granularity text",
        "86e7b5a82ff427a64befc27116ea413b",
    ),
    "market_reject_audit_mutation": (
        "",
        "d424fbd8975349adca4951faf9822929",
    ),
    "market_reject_superseded_discovery_write": (
        "",
        "26c4702c5c14f0f00816c67594a81584",
    ),
    "market_sha256": (
        "value jsonb",
        "96fd2a64d0e7a49328292c13b3708d98",
    ),
    "market_validate_dataset_registration": (
        "",
        "f1315be622fc736fe1d892850ed8d05b",
    ),
    "market_validate_discovery_attempt": (
        "",
        "a885693dcb97e6346ce49f9d909440fe",
    ),
    "market_validate_discovery_audit_insert": (
        "",
        "b3c77ca417a58f608d7a869547dd3782",
    ),
    "market_validate_discovery_chunk": (
        "",
        "c52d97167722c8845958b7b2169638f1",
    ),
    "market_validate_discovery_inventory_deferred": (
        "",
        "cbabdd794c4287fbe37d9562bd201ded",
    ),
    "market_validate_discovery_observation": (
        "",
        "7722c113c70b269f3df1e193d992ab09",
    ),
    "market_validate_discovery_plan": (
        "",
        "a27d41213e8b79e8d42c298561df8baf",
    ),
    "market_validate_discovery_provider_evidence": (
        "",
        "3ada738511255b66c867407858155038",
    ),
    "market_validate_discovery_seal_deferred": (
        "",
        "c06d697d25a9884c226938876708d2fe",
    ),
    "market_validate_discovery_supersession": (
        "",
        "915337e93db3e0a76a21f31c35ecab6c",
    ),
    "market_validate_discovery_terminal_run": (
        "",
        "ebbd7291f5f12c7f01f98fe29d01e5f3",
    ),
    "market_validate_historical_attempt": (
        "",
        "46a0c012e6bd1a63bae6824a45543711",
    ),
    "market_validate_historical_chunk": (
        "",
        "a7297e15766bb5bdbfc4f4cfe1aa137c",
    ),
    "market_validate_historical_dataset": (
        "",
        "b1d0e6d43782b0253940fd0fb8a65798",
    ),
    "market_validate_historical_plan": (
        "",
        "b27245e772c8800f32f0608277c18b05",
    ),
    "market_validate_replacement_canary_attempt": (
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer, new_idempotency_key text, new_ingestion_run_id bigint",
        "8236775a8308605a59f7e2cc3a6823d1",
    ),
}
REQUIRED_0017_TRIGGERS = {
    (
        "market_auditevent",
        "market_auditevent_append_only",
    ): "d6c72527049739e278a76c144db73685",
    (
        "market_auditevent",
        "market_discovery_audit_immutable",
    ): "9e04e08b33ba7fdba47075343422c7f6",
    (
        "market_auditevent",
        "market_discovery_audit_no_truncate",
    ): "77f26dd2ac3edc1df5eac1117ec9c4b8",
    (
        "market_auditevent",
        "market_discovery_audit_validate",
    ): "40a061306928fdc23f5018034229acd1",
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
        "market_ingestionrun",
        "market_discovery_run_terminal",
    ): "f7fac0b7a1b393de30461d5dfc89c978",
    (
        "market_ingestionrun",
        "market_ingestion_run_enforce",
    ): "ee6b757a9e76e7e25a90c1f809e85fa6",
}
# Verbatim pg_proc.prosrc of the 0016-state superseded-write rejection and
# the 0013-state seal validator, restored byte-identically by the empty
# reversal.
REJECT_SUPERSEDED_0016_PROSRC = r"""
        DECLARE plan_key bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key:=NEW.id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoverychunk' THEN
            plan_key:=NEW.plan_id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
            SELECT plan_id INTO STRICT plan_key FROM market_historicaldiscoverychunk
              WHERE id=NEW.chunk_id;
          ELSE
            plan_key:=NEW.plan_id;
          END IF;
          PERFORM market_discovery_plan_xact_lock(plan_key);
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE superseded_plan_id=plan_key)
          THEN RAISE EXCEPTION 'superseded discovery plans reject new writes'; END IF;
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE replacement_plan_id=plan_key) THEN
            IF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
              PERFORM market_validate_replacement_canary_attempt(
                plan_key, NEW.chunk_id, NEW.attempt_number, NEW.idempotency_key,
                NEW.ingestion_run_id);
            ELSIF TG_TABLE_NAME IN ('market_historicaldiscoveryapproval',
                                    'market_historicaldiscoveryregistration') THEN
              RAISE EXCEPTION
                'supersession replacement plans reject approval until governed activation';
            ELSIF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
              RAISE EXCEPTION
                'supersession replacement plans reject sealing until governed activation';
            END IF;
          END IF;
          RETURN NEW;
        END """
SEAL_0013_PROSRC = r"""
        DECLARE plan_key bigint; plan_row record; approval_row record; registration_row record;
                permission_ok boolean; chunk_count integer; inventory_count integer;
                running_count integer; chunk_manifest jsonb; semantic_manifest jsonb;
                operational_manifest jsonb; chunk_hash text; semantic_hash text; operational_hash text;
                approver_username text; expected_approval jsonb; expected_registration jsonb;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key := NEW.id;
          ELSE
            plan_key := NEW.plan_id;
          END IF;
          SELECT * INTO STRICT plan_row FROM market_historicaldiscoveryplan WHERE id=plan_key;
          SELECT * INTO approval_row FROM market_historicaldiscoveryapproval WHERE plan_id=plan_key;
          SELECT * INTO registration_row FROM market_historicaldiscoveryregistration WHERE plan_id=plan_key;
          IF approval_row.id IS NULL OR registration_row.id IS NULL OR plan_row.sealed_at IS NULL THEN
            RAISE EXCEPTION 'approval, registration and sealing must commit atomically';
          END IF;
          SELECT u.is_active AND (u.is_superuser OR EXISTS(
            SELECT 1 FROM auth_user_user_permissions up JOIN auth_permission perm ON perm.id=up.permission_id
             JOIN django_content_type ct ON ct.id=perm.content_type_id
             WHERE up.user_id=u.id AND perm.codename='approve_historical_discovery'
               AND ct.app_label='market' AND ct.model='historicaldiscoveryplan') OR EXISTS(
            SELECT 1 FROM auth_user_groups ug JOIN auth_group_permissions gp ON gp.group_id=ug.group_id
             JOIN auth_permission perm ON perm.id=gp.permission_id
             JOIN django_content_type ct ON ct.id=perm.content_type_id
             WHERE ug.user_id=u.id AND perm.codename='approve_historical_discovery'
               AND ct.app_label='market' AND ct.model='historicaldiscoveryplan'))
            INTO permission_ok FROM auth_user u WHERE u.id=approval_row.approved_by_id;
          SELECT username INTO approver_username FROM auth_user
            WHERE id=approval_row.approved_by_id;
          SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
              'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
              'canonical_request',c.canonical_request,
              'canonical_request_sha256',c.canonical_request_sha256) ORDER BY c.ordinal),'[]'),
              coalesce(jsonb_agg(jsonb_build_object('logical_discovery_key',c.logical_key,
              'semantic_inventory_sha256',inv.semantic_inventory_sha256) ORDER BY c.ordinal)
              FILTER (WHERE inv.id IS NOT NULL),'[]'),count(inv.id)
            INTO chunk_count,chunk_manifest,semantic_manifest,inventory_count
            FROM market_historicaldiscoverychunk c LEFT JOIN market_historicaltimestampinventory inv
              ON inv.chunk_id=c.id WHERE c.plan_id=plan_key;
          SELECT count(*) INTO running_count FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE c.plan_id=plan_key AND r.status='running';
          SELECT coalesce(jsonb_agg(e.operational_evidence_sha256
                   ORDER BY c.ordinal,a.attempt_number),'[]') INTO operational_manifest
            FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_historicaldiscoveryproviderevidence e ON e.attempt_id=a.id
            WHERE c.plan_id=plan_key;
          chunk_hash:=market_sha256(chunk_manifest); semantic_hash:=market_sha256(semantic_manifest);
          operational_hash:=market_sha256(operational_manifest);
          expected_approval:=jsonb_build_object(
            'identity','failed-break-phase-2b1r-discovery-approval-v1',
            'plan_sha256',plan_row.sha256,
            'global_semantic_inventory_sha256',semantic_hash,
            'accepted_operational_evidence_set_sha256',operational_hash,
            'cross_series_report_sha256',registration_row.cross_series_report_sha256,
            'approved_by',approver_username,
            'approved_at',market_discovery_operational_timestamp(approval_row.approved_at));
          expected_registration:=jsonb_build_object(
            'plan_sha256',plan_row.sha256,'approval_sha256',approval_row.sha256,
            'ordered_chunk_manifest_sha256',chunk_hash,
            'global_semantic_inventory_sha256',semantic_hash,
            'accepted_operational_evidence_set_sha256',operational_hash,
            'cross_series_report_sha256',registration_row.cross_series_report_sha256,
            'registered_at',market_discovery_operational_timestamp(registration_row.registered_at));
          IF NOT coalesce(permission_ok,false) OR chunk_count<>plan_row.declared_chunk_count
             OR inventory_count<>chunk_count OR running_count<>0
             OR chunk_manifest<>plan_row.canonical_request_manifest
             OR approval_row.global_semantic_inventory_sha256<>semantic_hash
             OR approval_row.accepted_operational_evidence_set_sha256<>operational_hash
             OR approval_row.payload IS DISTINCT FROM expected_approval
             OR approval_row.sha256 IS DISTINCT FROM market_sha256(expected_approval)
             OR registration_row.approval_id<>approval_row.id
             OR registration_row.ordered_chunk_manifest_sha256<>chunk_hash
             OR registration_row.global_semantic_inventory_sha256<>semantic_hash
             OR registration_row.accepted_operational_evidence_set_sha256<>operational_hash
             OR approval_row.payload->>'cross_series_report_sha256' IS DISTINCT FROM
                registration_row.cross_series_report_sha256
             OR registration_row.payload IS DISTINCT FROM expected_registration
             OR registration_row.report_sha256 IS DISTINCT FROM
                market_sha256(expected_registration)
             OR registration_row.registered_at<>plan_row.sealed_at
          THEN RAISE EXCEPTION 'discovery seal does not reconstruct'; END IF;
          RETURN NULL;
        END """
# Gate 5 activation bodies. The superseded-write rejection delegates
# approval, registration and sealing of the replacement plan to the governed
# Gate 5 validation instead of rejecting unconditionally. The Gate 5
# validation replays every inventory hash from the immutable observation
# rows and every operational hash from the attempt, run, provider-evidence
# and audit facts before constructing the pinned global identities, so
# stored summary hashes are never trusted. The deferred seal validator
# re-runs that validation at commit time, binds the committed
# approval-decision artifact into the approval payload identity, and pins
# the cross-series completion-summary hash and the complete observation
# count.
REJECT_SUPERSEDED_GATE5_PROSRC = r"""
        DECLARE plan_key bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key:=NEW.id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoverychunk' THEN
            plan_key:=NEW.plan_id;
          ELSIF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
            SELECT plan_id INTO STRICT plan_key FROM market_historicaldiscoverychunk
              WHERE id=NEW.chunk_id;
          ELSE
            plan_key:=NEW.plan_id;
          END IF;
          PERFORM market_discovery_plan_xact_lock(plan_key);
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE superseded_plan_id=plan_key)
          THEN RAISE EXCEPTION 'superseded discovery plans reject new writes'; END IF;
          IF EXISTS(SELECT 1 FROM market_historicaldiscoverysupersession
                    WHERE replacement_plan_id=plan_key) THEN
            IF TG_TABLE_NAME='market_historicaldiscoveryattempt' THEN
              PERFORM market_validate_replacement_canary_attempt(
                plan_key, NEW.chunk_id, NEW.attempt_number, NEW.idempotency_key,
                NEW.ingestion_run_id);
            ELSIF TG_TABLE_NAME IN ('market_historicaldiscoveryapproval',
                                    'market_historicaldiscoveryregistration',
                                    'market_historicaldiscoveryplan') THEN
              PERFORM market_validate_gate5_registration(plan_key);
            END IF;
          END IF;
          RETURN NEW;
        END """
SEAL_GATE5_PROSRC = r"""
        DECLARE plan_key bigint; plan_row record; approval_row record; registration_row record;
                permission_ok boolean; chunk_count integer; inventory_count integer;
                running_count integer; chunk_manifest jsonb; semantic_manifest jsonb;
                operational_manifest jsonb; chunk_hash text; semantic_hash text; operational_hash text;
                approver_username text; expected_approval jsonb; expected_registration jsonb;
                gate5_observation_count bigint;
        BEGIN
          IF TG_TABLE_NAME='market_historicaldiscoveryplan' THEN
            plan_key := NEW.id;
          ELSE
            plan_key := NEW.plan_id;
          END IF;
          PERFORM market_validate_gate5_registration(plan_key);
          SELECT * INTO STRICT plan_row FROM market_historicaldiscoveryplan WHERE id=plan_key;
          SELECT * INTO approval_row FROM market_historicaldiscoveryapproval WHERE plan_id=plan_key;
          SELECT * INTO registration_row FROM market_historicaldiscoveryregistration WHERE plan_id=plan_key;
          IF approval_row.id IS NULL OR registration_row.id IS NULL OR plan_row.sealed_at IS NULL THEN
            RAISE EXCEPTION 'approval, registration and sealing must commit atomically';
          END IF;
          SELECT u.is_active AND (u.is_superuser OR EXISTS(
            SELECT 1 FROM auth_user_user_permissions up JOIN auth_permission perm ON perm.id=up.permission_id
             JOIN django_content_type ct ON ct.id=perm.content_type_id
             WHERE up.user_id=u.id AND perm.codename='approve_historical_discovery'
               AND ct.app_label='market' AND ct.model='historicaldiscoveryplan') OR EXISTS(
            SELECT 1 FROM auth_user_groups ug JOIN auth_group_permissions gp ON gp.group_id=ug.group_id
             JOIN auth_permission perm ON perm.id=gp.permission_id
             JOIN django_content_type ct ON ct.id=perm.content_type_id
             WHERE ug.user_id=u.id AND perm.codename='approve_historical_discovery'
               AND ct.app_label='market' AND ct.model='historicaldiscoveryplan'))
            INTO permission_ok FROM auth_user u WHERE u.id=approval_row.approved_by_id;
          SELECT username INTO approver_username FROM auth_user
            WHERE id=approval_row.approved_by_id;
          SELECT count(*),coalesce(jsonb_agg(jsonb_build_object(
              'ordinal',c.ordinal,'logical_discovery_key',c.logical_key,
              'canonical_request',c.canonical_request,
              'canonical_request_sha256',c.canonical_request_sha256) ORDER BY c.ordinal),'[]'),
              coalesce(jsonb_agg(jsonb_build_object('logical_discovery_key',c.logical_key,
              'semantic_inventory_sha256',inv.semantic_inventory_sha256) ORDER BY c.ordinal)
              FILTER (WHERE inv.id IS NOT NULL),'[]'),count(inv.id)
            INTO chunk_count,chunk_manifest,semantic_manifest,inventory_count
            FROM market_historicaldiscoverychunk c LEFT JOIN market_historicaltimestampinventory inv
              ON inv.chunk_id=c.id WHERE c.plan_id=plan_key;
          SELECT count(*) INTO running_count FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE c.plan_id=plan_key AND r.status='running';
          SELECT coalesce(jsonb_agg(e.operational_evidence_sha256
                   ORDER BY c.ordinal,a.attempt_number),'[]') INTO operational_manifest
            FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_historicaldiscoveryproviderevidence e ON e.attempt_id=a.id
            WHERE c.plan_id=plan_key;
          chunk_hash:=market_sha256(chunk_manifest); semantic_hash:=market_sha256(semantic_manifest);
          operational_hash:=market_sha256(operational_manifest);
          expected_approval:=jsonb_build_object(
            'identity','failed-break-phase-2b1r-discovery-approval-v1',
            'plan_sha256',plan_row.sha256,
            'global_semantic_inventory_sha256',semantic_hash,
            'accepted_operational_evidence_set_sha256',operational_hash,
            'cross_series_report_sha256',registration_row.cross_series_report_sha256,
            'approval_decision_sha256','d85029bd86690859e0bf3be3a38f36033e6c1fd6fdd4035d6f2944d4e9e14aea',
            'approved_by',approver_username,
            'approved_at',market_discovery_operational_timestamp(approval_row.approved_at));
          expected_registration:=jsonb_build_object(
            'plan_sha256',plan_row.sha256,'approval_sha256',approval_row.sha256,
            'ordered_chunk_manifest_sha256',chunk_hash,
            'global_semantic_inventory_sha256',semantic_hash,
            'accepted_operational_evidence_set_sha256',operational_hash,
            'cross_series_report_sha256',registration_row.cross_series_report_sha256,
            'registered_at',market_discovery_operational_timestamp(registration_row.registered_at));
          IF NOT coalesce(permission_ok,false) OR chunk_count<>plan_row.declared_chunk_count
             OR inventory_count<>chunk_count OR running_count<>0
             OR chunk_manifest<>plan_row.canonical_request_manifest
             OR approval_row.global_semantic_inventory_sha256<>semantic_hash
             OR approval_row.accepted_operational_evidence_set_sha256<>operational_hash
             OR approval_row.payload IS DISTINCT FROM expected_approval
             OR approval_row.sha256 IS DISTINCT FROM market_sha256(expected_approval)
             OR registration_row.approval_id<>approval_row.id
             OR registration_row.ordered_chunk_manifest_sha256<>chunk_hash
             OR registration_row.global_semantic_inventory_sha256<>semantic_hash
             OR registration_row.accepted_operational_evidence_set_sha256<>operational_hash
             OR approval_row.payload->>'cross_series_report_sha256' IS DISTINCT FROM
                registration_row.cross_series_report_sha256
             OR registration_row.payload IS DISTINCT FROM expected_registration
             OR registration_row.report_sha256 IS DISTINCT FROM
                market_sha256(expected_registration)
             OR registration_row.registered_at<>plan_row.sealed_at
          THEN RAISE EXCEPTION 'discovery seal does not reconstruct'; END IF;
          SELECT count(*) INTO gate5_observation_count
            FROM market_historicaltimestampobservation o
            JOIN market_historicaltimestampinventory i ON i.id=o.inventory_id
            JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
            WHERE c.plan_id=plan_key;
          IF registration_row.cross_series_report_sha256<>'d267326c7d62e43fffaa610af118d52c7754af357a888a1c95cf3d24b16ae32d'
             OR chunk_hash<>'04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR semantic_hash<>'78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c'
             OR operational_hash<>'a650dd977f0f2c79cbad2cb476fe36610a0fc0c2f372107b541882d0b342c878'
             OR gate5_observation_count<>364953
          THEN RAISE EXCEPTION 'gate5 seal does not reconstruct'; END IF;
          RETURN NULL;
        END """
GATE5_REGISTRATION_PROSRC = r"""
        DECLARE plan_row record; chunk_count integer; inventory_count integer;
                observation_count bigint; running_count integer; attempt_count integer;
                supersession_count integer; semantic_hash text; operational_hash text;
                canary_chunk_id bigint; canary_failed integer; canary_succeeded integer;
                canary_attempts integer; canary_inventories integer;
                bad_inventories integer; bad_evidence integer; evidence_count integer;
        BEGIN
          SELECT * INTO STRICT plan_row FROM market_historicaldiscoveryplan
            WHERE id=plan_key;
          IF plan_row.sha256<>'2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
             OR plan_row.identity<>'failed-break-phase-2b1r-discovery-plan-v2'
             OR plan_row.version<>'phase-2b1r-discovery-v2'
             OR plan_row.canonical_request_manifest_sha256<>'04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR plan_row.declared_chunk_count<>132
             OR market_sha256(plan_row.payload)<>plan_row.sha256
             OR market_sha256(plan_row.payload->'requests')
                <>plan_row.canonical_request_manifest_sha256
          THEN RAISE EXCEPTION
            'only the approved replacement discovery plan may be approved'; END IF;
          SELECT count(*) INTO supersession_count
            FROM market_historicaldiscoverysupersession
            WHERE replacement_plan_id=plan_row.id
              AND superseded_plan_sha256='292556a591024876c7051212d1c6886cd026a097e141295e9b60257fc5402b33'
              AND replacement_plan_sha256=plan_row.sha256;
          IF supersession_count<>1 THEN RAISE EXCEPTION
            'gate5 supersession lineage does not reconstruct'; END IF;
          SELECT c.id INTO canary_chunk_id FROM market_historicaldiscoverychunk c
            WHERE c.plan_id=plan_row.id
              AND c.logical_key='63db29db49868205e76c52507dab8da30d4a740fac41e709a1edbb1ea100b88d'
              AND c.canonical_request_sha256='3ec01ff455aeef4b6977fb7350dfa8fd98dae744a886c22ad84d597947677ff1'
              AND c.ordinal=2 AND c.granularity='H1';
          SELECT count(*) FILTER (WHERE a.attempt_number=1 AND r.status='failed'
                   AND r.failure_reason='DISCOVERY_STRUCTURE_INVALID'
                   AND r.fetched_count=2932 AND r.stored_count=0
                   AND r.rejected_count=2932),
                 count(*) FILTER (WHERE a.attempt_number=2 AND r.status='succeeded'
                   AND r.fetched_count=2932 AND r.stored_count=2932
                   AND r.rejected_count=0),
                 count(*)
            INTO canary_failed, canary_succeeded, canary_attempts
            FROM market_historicaldiscoveryattempt a
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE a.chunk_id=canary_chunk_id;
          SELECT count(*) INTO canary_inventories
            FROM market_historicaltimestampinventory i
            JOIN market_historicaldiscoveryattempt a ON a.id=i.accepted_attempt_id
            WHERE i.chunk_id=canary_chunk_id AND a.attempt_number=2
              AND i.observation_count=2932;
          IF canary_chunk_id IS NULL OR canary_failed<>1 OR canary_succeeded<>1
             OR canary_attempts<>2 OR canary_inventories<>1
          THEN RAISE EXCEPTION 'gate5 canary lineage does not reconstruct'; END IF;
          SELECT count(*), count(inv.id) INTO chunk_count, inventory_count
            FROM market_historicaldiscoverychunk c
            LEFT JOIN market_historicaltimestampinventory inv ON inv.chunk_id=c.id
            WHERE c.plan_id=plan_row.id;
          SELECT count(*) INTO observation_count
            FROM market_historicaltimestampobservation o
            JOIN market_historicaltimestampinventory i ON i.id=o.inventory_id
            JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
            WHERE c.plan_id=plan_row.id;
          SELECT count(*) FILTER (WHERE r.status='running'), count(*)
            INTO running_count, attempt_count
            FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
            WHERE c.plan_id=plan_row.id;
          SELECT count(*) FILTER (WHERE replay.observation_count<>replay.replayed_count
                   OR replay.timestamp_set_sha256<>replay.replayed_timestamp
                   OR replay.structural_observation_sha256<>replay.replayed_structural
                   OR replay.semantic_inventory_sha256<>replay.replayed_semantic),
                 market_sha256(coalesce(jsonb_agg(jsonb_build_object(
                   'logical_discovery_key',replay.logical_key,
                   'semantic_inventory_sha256',replay.replayed_semantic)
                   ORDER BY replay.ordinal),'[]'))
            INTO bad_inventories, semantic_hash
            FROM (
              SELECT c.ordinal, c.logical_key, i.observation_count,
                     i.timestamp_set_sha256, i.structural_observation_sha256,
                     i.semantic_inventory_sha256,
                     obs.replayed_count, obs.replayed_timestamp, obs.replayed_structural,
                     market_sha256(jsonb_build_object(
                       'logical_discovery_key',c.logical_key,
                       'canonical_request_sha256',c.canonical_request_sha256,
                       'observation_count',obs.replayed_count,
                       'timestamp_set_sha256',obs.replayed_timestamp,
                       'structural_observation_sha256',obs.replayed_structural))
                       AS replayed_semantic
                FROM market_historicaltimestampinventory i
                JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
                CROSS JOIN LATERAL (
                  SELECT count(*) AS replayed_count,
                         market_sha256(coalesce(jsonb_agg(
                           market_discovery_timestamp(o.timestamp)
                           ORDER BY o.timestamp),'[]')) AS replayed_timestamp,
                         market_sha256(coalesce(jsonb_agg(jsonb_build_object(
                           'timestamp',market_discovery_timestamp(o.timestamp),
                           'complete',o.complete,'volume',o.volume,
                           'bid_present',o.bid_present,'ask_present',o.ask_present)
                           ORDER BY o.timestamp),'[]')) AS replayed_structural
                    FROM market_historicaltimestampobservation o
                    WHERE o.inventory_id=i.id) obs
                WHERE c.plan_id=plan_row.id) replay;
          IF bad_inventories<>0 THEN RAISE EXCEPTION
            'gate5 inventory replay does not reconstruct'; END IF;
          SELECT count(*),
                 count(*) FILTER (WHERE replay.status='running'
                   OR replay.event_count<>1
                   OR replay.event_payload->>'event_sha256'<>replay.terminal_event_sha256
                   OR market_sha256(replay.event_payload-'event_sha256')
                      <>replay.terminal_event_sha256
                   OR replay.operational_evidence_sha256<>replay.replayed_operational),
                 market_sha256(coalesce(jsonb_agg(replay.replayed_operational
                   ORDER BY replay.ordinal, replay.attempt_number),'[]'))
            INTO evidence_count, bad_evidence, operational_hash
            FROM (
              SELECT c.ordinal, a.attempt_number, r.status,
                     e.terminal_event_sha256, e.operational_evidence_sha256,
                     ev.event_count, ev.event_payload,
                     market_sha256(jsonb_build_object(
                       'logical_discovery_key',c.logical_key,
                       'attempt_number',a.attempt_number,
                       'attempt_idempotency_key',a.idempotency_key,
                       'run_id',r.id,
                       'run_request_manifest_hash',r.request_manifest_hash,
                       'canonical_request_sha256',e.canonical_request_sha256,
                       'endpoint_identity',e.endpoint_identity,
                       'environment',e.environment,
                       'http_method',e.http_method,'http_status',e.http_status,
                       'provider_request_id',e.provider_request_id,
                       'unavailable_fields',e.unavailable_fields,
                       'started_at',market_discovery_operational_timestamp(r.started_at),
                       'finished_at',market_discovery_operational_timestamp(r.finished_at),
                       'terminal_status',r.status,
                       'failure_code',nullif(r.failure_reason,''),
                       'terminal_event_sha256',e.terminal_event_sha256))
                       AS replayed_operational
                FROM market_historicaldiscoveryattempt a
                JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
                JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
                JOIN market_historicaldiscoveryproviderevidence e ON e.attempt_id=a.id
                CROSS JOIN LATERAL (
                  SELECT count(*) AS event_count,
                         (min(audit.payload::text))::jsonb AS event_payload
                    FROM market_auditevent audit
                    WHERE audit.subject_type='HistoricalDiscoveryAttempt'
                      AND audit.subject_id=a.id::text
                      AND audit.event_type IN ('market.historical_discovery_succeeded',
                                               'market.historical_discovery_failed')) ev
                WHERE c.plan_id=plan_row.id) replay;
          IF bad_evidence<>0 OR evidence_count<>attempt_count THEN RAISE EXCEPTION
            'gate5 operational evidence replay does not reconstruct'; END IF;
          IF chunk_count<>132 OR inventory_count<>132 OR observation_count<>364953
             OR running_count<>0 OR attempt_count<>133
             OR semantic_hash<>'78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c'
             OR operational_hash<>'a650dd977f0f2c79cbad2cb476fe36610a0fc0c2f372107b541882d0b342c878'
          THEN RAISE EXCEPTION
            'gate5 registration state does not reconstruct'; END IF;
        END"""


def _governance():
    return import_module("market.migrations.0014_historical_discovery_supersession")


def _execute(schema_editor, statement):
    # psycopg parses % as a placeholder even with no params; escape literal
    # percent signs so restored verbatim bodies keep single % once stored.
    schema_editor.execute(statement.replace("%", "%%"))


def _require_no_registration_evidence(schema_editor, action):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """SELECT EXISTS(SELECT 1 FROM market_historicaldiscoveryapproval)
                   OR EXISTS(SELECT 1 FROM market_historicaldiscoveryregistration)
                   OR EXISTS(SELECT 1 FROM market_historicaldiscoveryplan
                             WHERE sealed_at IS NOT NULL)"""
        )
        if cursor.fetchone()[0]:
            raise RuntimeError(
                f"approval, registration or sealing evidence prohibits gate5 {action}"
            )


def preflight_registration_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    governance = _governance()
    problems = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [list(REQUIRED_0017_FUNCTIONS)])
        found_functions = {}
        for name, identity_arguments, fingerprint in cursor.fetchall():
            found_functions.setdefault(name, []).append((identity_arguments, fingerprint))
        for name, expected in sorted(REQUIRED_0017_FUNCTIONS.items()):
            candidates = found_functions.get(name, [])
            if not candidates:
                problems.append(f"required 0017 function {name} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0017 function {name} has ambiguous overloads")
            elif candidates[0] != tuple(expected):
                problems.append(f"required 0017 function {name} does not match its 0017 definition")
        cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
        found_triggers = {}
        for table, name, fingerprint in cursor.fetchall():
            found_triggers.setdefault((table, name), []).append(fingerprint)
        for (table, name), expected in sorted(REQUIRED_0017_TRIGGERS.items()):
            candidates = found_triggers.get((table, name), [])
            if not candidates:
                problems.append(f"required 0017 trigger {name} on {table} is missing")
            elif len(candidates) > 1:
                problems.append(f"required 0017 trigger {name} on {table} is ambiguous")
            elif candidates[0] != expected:
                problems.append(
                    f"required 0017 trigger {name} on {table} does not match its 0017 definition"
                )
    if problems:
        raise RuntimeError(
            "migration 0018 preflight rejected the current catalog: " + "; ".join(problems)
        )
    _require_no_registration_evidence(schema_editor, "activation")


def install_registration_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _execute(
        schema_editor,
        "CREATE FUNCTION market_validate_gate5_registration(plan_key bigint) "
        "RETURNS void AS $governed$" + GATE5_REGISTRATION_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_reject_superseded_discovery_write() "
        "RETURNS trigger AS $governed$" + REJECT_SUPERSEDED_GATE5_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_discovery_seal_deferred() "
        "RETURNS trigger AS $governed$" + SEAL_GATE5_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )


def remove_registration_activation(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    _require_no_registration_evidence(schema_editor, "reversal")
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_reject_superseded_discovery_write() "
        "RETURNS trigger AS $governed$" + REJECT_SUPERSEDED_0016_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "CREATE OR REPLACE FUNCTION market_validate_discovery_seal_deferred() "
        "RETURNS trigger AS $governed$" + SEAL_0013_PROSRC + "$governed$ "
        "LANGUAGE plpgsql;",
    )
    _execute(
        schema_editor,
        "DROP FUNCTION market_validate_gate5_registration(bigint);",
    )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("market", "0017_provider_observed_full_discovery_activation"),
    ]

    operations = [
        migrations.RunPython(preflight_registration_activation, migrations.RunPython.noop),
        migrations.RunPython(install_registration_activation, remove_registration_activation),
    ]
