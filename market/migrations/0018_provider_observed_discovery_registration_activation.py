from importlib import import_module

from django.db import migrations

# Full portable fingerprints of the exact 0017-state governance this
# migration depends on, captured with the 0014 fingerprint queries from a
# catalog migrated exactly through 0017.
REQUIRED_0017_FUNCTIONS = {
    "market_canonical_json": ("value jsonb", "aa43ea03a68b240dfcda6e2404c500a6"),
    "market_discovery_operational_timestamp": (
        "value timestamp with time zone",
        "0ade13a9b0800de89465ec203f3a6f45",
    ),
    "market_discovery_plan_xact_lock": ("plan_key bigint", "049915d1c7640a273f7c1946d90c272a"),
    "market_reject_superseded_discovery_write": ("", "26c4702c5c14f0f00816c67594a81584"),
    "market_sha256": ("value jsonb", "96fd2a64d0e7a49328292c13b3708d98"),
    "market_validate_discovery_plan": ("", "a27d41213e8b79e8d42c298561df8baf"),
    "market_validate_discovery_seal_deferred": ("", "c06d697d25a9884c226938876708d2fe"),
    "market_validate_replacement_canary_attempt": (
        "plan_key bigint, attempt_chunk_id bigint, new_attempt_number integer,"
        " new_idempotency_key text, new_ingestion_run_id bigint",
        "8236775a8308605a59f7e2cc3a6823d1",
    ),
}
REQUIRED_0017_TRIGGERS = {
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
# Gate 5 validation instead of rejecting unconditionally; the deferred seal
# validator additionally re-validates the Gate 5 state and pins the exact
# approved identities, the committed approval-decision artifact hash and the
# complete observation count at commit time.
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
          IF registration_row.cross_series_report_sha256<>'d85029bd86690859e0bf3be3a38f36033e6c1fd6fdd4035d6f2944d4e9e14aea'
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
          SELECT market_sha256(coalesce(jsonb_agg(jsonb_build_object(
                   'logical_discovery_key',c.logical_key,
                   'semantic_inventory_sha256',inv.semantic_inventory_sha256)
                   ORDER BY c.ordinal) FILTER (WHERE inv.id IS NOT NULL),'[]'))
            INTO semantic_hash
            FROM market_historicaldiscoverychunk c
            LEFT JOIN market_historicaltimestampinventory inv ON inv.chunk_id=c.id
            WHERE c.plan_id=plan_row.id;
          SELECT market_sha256(coalesce(jsonb_agg(e.operational_evidence_sha256
                   ORDER BY c.ordinal,a.attempt_number),'[]')) INTO operational_hash
            FROM market_historicaldiscoveryattempt a
            JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
            JOIN market_historicaldiscoveryproviderevidence e ON e.attempt_id=a.id
            WHERE c.plan_id=plan_row.id;
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
