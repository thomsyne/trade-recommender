"""Gate 8D3': the post-discovery registration authority for the successor plan.

Migration 0023 opened successor *discovery* and deliberately withheld
everything after it. This grants exactly what it withheld and nothing more:
approval, registration and the atomic sealing transition, for one plan — the
independently accepted successor outcome — and refuses every other.

The predecessor v2 authority is untouched. Its statements in both governed
functions are preserved byte for byte; the successor is a separate positive
branch that returns before the predecessor branch is reached, so no predecessor
predicate is relaxed, generalized or made configurable.

Authority comes from the literals below and from predicates that recompute the
outcome from governed raw rows. Nothing is read from the approval or
registration row: those rows are validated against the reconstruction, never
consulted for it. The one value they do supply, the cross-series report digest,
is compared with the accepted Gate 8D3 artifact digest as an exact literal, so
that comparison is a real catalog predicate rather than provenance.

Provenance, enforced in Python by the artifact loader rather than here:
  Gate 8D3 outcome artifact
    docs/strategy/failed-break/v1/phase-2b1r-gate8d3-successor-discovery-outcome.json
    file SHA-256   b13fe357e5c2dec3450a6fc15cf755d6a940e6b83af8592cfdedaa9cc74156c5
    embedded self-hash 30c11d7470bd63003ebc71a71da04e754d85d70671050f819a869cf985e63692
The database compares the file digest only where it appears as a literal
predicate below; it does not read the file.

Applying this migration installs catalog objects only. It creates, alters and
deletes no row, and by itself changes no persisted evidence.
"""

from importlib import import_module

from django.db import migrations

SUCCESSOR_PLAN_SHA256 = "e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88"
SUCCESSOR_PLAN_IDENTITY = "failed-break-phase-2b1r-discovery-plan-v3"
SUCCESSOR_PLAN_VERSION = "phase-2b1r-discovery-v3"
SUCCESSOR_MANIFEST_SHA256 = "6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0"
SUCCESSOR_SEMANTIC_INVENTORY_SHA256 = (
    "f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427"
)
SUCCESSOR_OPERATIONAL_EVIDENCE_SHA256 = (
    "5653e5be68d47d793ae68e774467a2fdb5b06edd60e6adecbf7c02fd2697235b"
)
SUCCESSOR_RESTRICTED_OVERLAP_SHA256 = (
    "c5aa25515578996e01218c4c193949e608fcdd3b378b313ed90369f1dd31eec1"
)
GATE8D3_ARTIFACT_SHA256 = "b13fe357e5c2dec3450a6fc15cf755d6a940e6b83af8592cfdedaa9cc74156c5"

SUCCESSOR_CHUNK_COUNT = 132
SUCCESSOR_ATTEMPT_COUNT = 132
SUCCESSOR_OBSERVATION_COUNT = 365055
SUCCESSOR_GRANULARITY_OBSERVATIONS = {"D": 17412, "H1": 344817, "W": 2826}
SUCCESSOR_WARMUP = {"earlier": 17, "predecessor": 8, "combined": 25, "required": 14}

GATE5_SIGNATURE = "market_validate_gate5_registration(plan_key bigint)"
SEAL_SIGNATURE = "market_validate_discovery_seal_deferred()"

# The complete 0023 catalog this migration requires, and the two bodies it
# replaces, embedded so an empty reversal restores them byte for byte.
REQUIRED_FUNCTION_COUNT = 56
REQUIRED_TRIGGER_COUNT = 74
REPLACED_FUNCTIONS = (
    "market_validate_gate5_registration",
    "market_validate_discovery_seal_deferred",
)

PRIOR_GATE5_PROSRC = r"""
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

PRIOR_SEAL_PROSRC = r"""
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

SUCCESSOR_GATE5_PROSRC = r"""
        DECLARE plan_row record; chunk_count integer; inventory_count integer;
                observation_count bigint; running_count integer; attempt_count integer;
                supersession_count integer; semantic_hash text; operational_hash text;
                canary_chunk_id bigint; canary_failed integer; canary_succeeded integer;
                canary_attempts integer; canary_inventories integer;
                bad_inventories integer; bad_evidence integer; evidence_count integer;
                successor_distinct_chunks integer; successor_attempts_beyond integer;
                successor_succeeded integer; successor_evidence_rows integer;
                successor_audit_events integer; successor_bad_binding integer;
                successor_d bigint; successor_h1 bigint; successor_w bigint;
                successor_supersessions integer; successor_warm_instruments integer;
                successor_overlap text; predecessor_overlap text;
        BEGIN
          SELECT * INTO STRICT plan_row FROM market_historicaldiscoveryplan
            WHERE id=plan_key;
          -- Gate 8D3': the independently accepted successor outcome, and only it.
          -- Every predicate below is recomputed from governed raw rows and then
          -- compared with the exact accepted literal. Nothing is taken from the
          -- approval or registration row, which do not exist yet when this runs
          -- for the plan and carry no authority when they do.
          IF plan_row.sha256=
             'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88' THEN
            IF plan_row.identity<>'failed-break-phase-2b1r-discovery-plan-v3'
               OR plan_row.version<>'phase-2b1r-discovery-v3'
               OR plan_row.canonical_request_manifest_sha256<>
                  '6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0'
               OR plan_row.declared_chunk_count<>132
               OR market_sha256(plan_row.payload)<>plan_row.sha256
               OR market_sha256(plan_row.payload->'requests')
                  <>plan_row.canonical_request_manifest_sha256
            THEN RAISE EXCEPTION
              'only the accepted successor discovery plan may be approved'; END IF;
            -- The successor is not superseded and supersedes nothing: the
            -- v1->v2 lineage rule belongs to the predecessor branch alone.
            SELECT count(*) INTO successor_supersessions
              FROM market_historicaldiscoverysupersession
              WHERE superseded_plan_id=plan_row.id OR replacement_plan_id=plan_row.id;
            IF successor_supersessions<>0 THEN RAISE EXCEPTION
              'gate 8D3-prime requires an unsuperseded successor plan'; END IF;
            SELECT count(*), count(inv.id) INTO chunk_count, inventory_count
              FROM market_historicaldiscoverychunk c
              LEFT JOIN market_historicaltimestampinventory inv ON inv.chunk_id=c.id
              WHERE c.plan_id=plan_row.id;
            SELECT count(*), count(DISTINCT a.chunk_id),
                   count(*) FILTER (WHERE a.attempt_number<>1),
                   count(*) FILTER (WHERE r.status='succeeded'),
                   count(*) FILTER (WHERE r.status='running'),
                   count(*) FILTER (WHERE r.status IN ('failed','quarantined'))
              INTO attempt_count, successor_distinct_chunks, successor_attempts_beyond,
                   successor_succeeded, running_count, bad_evidence
              FROM market_historicaldiscoveryattempt a
              JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
              JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
              WHERE c.plan_id=plan_row.id;
            SELECT count(*) INTO successor_evidence_rows
              FROM market_historicaldiscoveryproviderevidence e
              JOIN market_historicaldiscoveryattempt a ON a.id=e.attempt_id
              JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
              WHERE c.plan_id=plan_row.id;
            SELECT count(*) INTO successor_audit_events
              FROM market_auditevent ev
              JOIN market_historicaldiscoveryattempt a ON ev.subject_id=a.id::text
              JOIN market_historicaldiscoverychunk c ON c.id=a.chunk_id
              WHERE c.plan_id=plan_row.id
                AND ev.subject_type='HistoricalDiscoveryAttempt'
                AND ev.event_type='market.historical_discovery_succeeded';
            -- an inventory counts only when it is bound to an attempt of its own
            -- chunk whose run succeeded
            SELECT count(*) INTO successor_bad_binding
              FROM market_historicaltimestampinventory i
              JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
              JOIN market_historicaldiscoveryattempt a ON a.id=i.accepted_attempt_id
              JOIN market_ingestionrun r ON r.id=a.ingestion_run_id
              WHERE c.plan_id=plan_row.id
                AND (a.chunk_id<>i.chunk_id OR r.status<>'succeeded');
            SELECT count(*) FILTER (WHERE c.granularity='D'),
                   count(*) FILTER (WHERE c.granularity='H1'),
                   count(*) FILTER (WHERE c.granularity='W'),
                   count(*)
              INTO successor_d, successor_h1, successor_w, observation_count
              FROM market_historicaltimestampobservation o
              JOIN market_historicaltimestampinventory i ON i.id=o.inventory_id
              JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
              WHERE c.plan_id=plan_row.id;
            IF chunk_count<>132 OR inventory_count<>132 OR attempt_count<>132
               OR successor_distinct_chunks<>132 OR successor_attempts_beyond<>0
               OR successor_succeeded<>132 OR running_count<>0 OR bad_evidence<>0
               OR successor_evidence_rows<>132 OR successor_audit_events<>132
               OR successor_bad_binding<>0 OR observation_count<>365055
               OR successor_d<>17412 OR successor_h1<>344817 OR successor_w<>2826
            THEN RAISE EXCEPTION
              'gate 8D3-prime successor completion does not reconstruct'; END IF;
            -- the inventory replay, reused verbatim from the predecessor branch
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
              'gate 8D3-prime inventory replay does not reconstruct'; END IF;
            SELECT count(*),
                   count(*) FILTER (WHERE replay.status<>'succeeded'
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
              'gate 8D3-prime operational evidence replay does not reconstruct'; END IF;
            -- warm-up: every instrument's extended first H1 window must carry 17
            -- completed eligible observations earlier than the predecessor start,
            -- and its predecessor counterpart 8, for 25 against the 14 required.
            SELECT count(*) INTO successor_warm_instruments FROM (
              SELECT ext.instrument_id
                FROM (SELECT c.instrument_id, count(*) FILTER (WHERE o.complete
                        AND o.timestamp<'2009-12-31T15:00:00Z'::timestamptz
                        AND o.timestamp<='2010-01-01T04:00:00Z'::timestamptz) AS earlier
                        FROM market_historicaldiscoverychunk c
                        JOIN market_historicaltimestampinventory i ON i.chunk_id=c.id
                        JOIN market_historicaltimestampobservation o ON o.inventory_id=i.id
                       WHERE c.plan_id=plan_row.id AND c.granularity='H1'
                         AND c.canonical_request->>'from'='2009-12-30T22:00:00Z'
                       GROUP BY c.instrument_id) ext
                JOIN (SELECT c.instrument_id, count(*) FILTER (WHERE o.complete
                        AND o.timestamp<='2010-01-01T04:00:00Z'::timestamptz) AS warm
                        FROM market_historicaldiscoverychunk c
                        JOIN market_historicaldiscoveryplan pp ON pp.id=c.plan_id
                        JOIN market_historicaltimestampinventory i ON i.chunk_id=c.id
                        JOIN market_historicaltimestampobservation o ON o.inventory_id=i.id
                       WHERE pp.sha256=
                             '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
                         AND c.granularity='H1'
                         AND c.canonical_request->>'from'='2009-12-31T15:00:00Z'
                       GROUP BY c.instrument_id) pw ON pw.instrument_id=ext.instrument_id
               WHERE ext.earlier=17 AND pw.warm=8 AND ext.earlier+pw.warm>=14
                 AND ext.earlier+pw.warm=25) warmed;
            IF successor_warm_instruments<>6 THEN RAISE EXCEPTION
              'gate 8D3-prime warm-up membership does not reconstruct'; END IF;
            -- restricted predecessor overlap: the successor evidence outside the
            -- extension must be byte-identical to the whole predecessor evidence.
            SELECT market_sha256(coalesce(jsonb_agg(jsonb_build_object(
                     'timestamp',market_discovery_timestamp(o.timestamp),
                     'complete',o.complete,'volume',o.volume,
                     'bid_present',o.bid_present,'ask_present',o.ask_present)
                     ORDER BY c.ordinal, o.timestamp),'[]'))
              INTO successor_overlap
              FROM market_historicaltimestampobservation o
              JOIN market_historicaltimestampinventory i ON i.id=o.inventory_id
              JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
             WHERE c.plan_id=plan_row.id
               AND NOT (c.granularity='H1'
                        AND c.canonical_request->>'from'='2009-12-30T22:00:00Z'
                        AND o.timestamp<'2009-12-31T15:00:00Z'::timestamptz);
            SELECT market_sha256(coalesce(jsonb_agg(jsonb_build_object(
                     'timestamp',market_discovery_timestamp(o.timestamp),
                     'complete',o.complete,'volume',o.volume,
                     'bid_present',o.bid_present,'ask_present',o.ask_present)
                     ORDER BY c.ordinal, o.timestamp),'[]'))
              INTO predecessor_overlap
              FROM market_historicaltimestampobservation o
              JOIN market_historicaltimestampinventory i ON i.id=o.inventory_id
              JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
              JOIN market_historicaldiscoveryplan pp ON pp.id=c.plan_id
             WHERE pp.sha256=
                   '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a';
            IF successor_overlap IS DISTINCT FROM predecessor_overlap
               OR successor_overlap<>
                  'c5aa25515578996e01218c4c193949e608fcdd3b378b313ed90369f1dd31eec1'
            THEN RAISE EXCEPTION
              'gate 8D3-prime restricted predecessor overlap does not reconstruct'; END IF;
            IF semantic_hash<>
               'f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427'
               OR operational_hash<>
                  '5653e5be68d47d793ae68e774467a2fdb5b06edd60e6adecbf7c02fd2697235b'
            THEN RAISE EXCEPTION
              'gate 8D3-prime successor aggregates do not reconstruct'; END IF;
            RETURN;
          END IF;
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

SUCCESSOR_SEAL_PROSRC = r"""
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
          -- Gate 8D3': the successor's accepted seal. The cross-series report is
          -- the accepted Gate 8D3 outcome artifact. This predicate compares the
          -- registration row's cross_series_report_sha256 with an exact reviewed
          -- literal whose value equals that artifact's file digest. PostgreSQL
          -- does not read, hash or otherwise verify the artifact file itself;
          -- the committed bytes are checked in Python by the governed loader.
          IF plan_row.sha256=
             'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88' THEN
            IF registration_row.cross_series_report_sha256<>
               'b13fe357e5c2dec3450a6fc15cf755d6a940e6b83af8592cfdedaa9cc74156c5'
               OR chunk_hash<>
                  '6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0'
               OR semantic_hash<>
                  'f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427'
               OR operational_hash<>
                  '5653e5be68d47d793ae68e774467a2fdb5b06edd60e6adecbf7c02fd2697235b'
               OR gate5_observation_count<>365055
            THEN RAISE EXCEPTION
              'gate 8D3-prime seal does not reconstruct'; END IF;
            RETURN NULL;
          END IF;
          IF registration_row.cross_series_report_sha256<>'d267326c7d62e43fffaa610af118d52c7754af357a888a1c95cf3d24b16ae32d'
             OR chunk_hash<>'04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427'
             OR semantic_hash<>'78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c'
             OR operational_hash<>'a650dd977f0f2c79cbad2cb476fe36610a0fc0c2f372107b541882d0b342c878'
             OR gate5_observation_count<>364953
          THEN RAISE EXCEPTION 'gate5 seal does not reconstruct'; END IF;
          RETURN NULL;
        END """


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


def _catalog(cursor):
    """The complete governed market catalog, by fingerprint."""
    governance = import_module("market.migrations.0014_historical_discovery_supersession")
    cursor.execute(
        r"SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
        r" WHERE n.nspname=current_schema() AND p.proname LIKE 'market\_%'"
    )
    names = [row[0] for row in cursor.fetchall()]
    cursor.execute(governance.FUNCTION_FINGERPRINT_SQL, [names])
    functions = {}
    for name, arguments, fingerprint in cursor.fetchall():
        functions.setdefault(name, []).append((arguments, fingerprint))
    cursor.execute(governance.TRIGGER_FINGERPRINT_SQL)
    triggers = {}
    for table, name, fingerprint in cursor.fetchall():
        if name.startswith("market_"):
            triggers.setdefault((table, name), []).append(fingerprint)
    return functions, triggers


def _preflight(cursor):
    """The complete installed 0023 catalog, or nothing happens."""
    functions, triggers = _catalog(cursor)
    if len(functions) != REQUIRED_FUNCTION_COUNT:
        raise RuntimeError(
            f"gate 8D3-prime requires the {REQUIRED_FUNCTION_COUNT}-function 0023 catalog,"
            f" found {len(functions)}"
        )
    if len(triggers) != REQUIRED_TRIGGER_COUNT:
        raise RuntimeError(
            f"gate 8D3-prime requires the {REQUIRED_TRIGGER_COUNT}-trigger 0023 catalog,"
            f" found {len(triggers)}"
        )
    overloaded = sorted(name for name, entries in functions.items() if len(entries) != 1)
    if overloaded:
        raise RuntimeError(f"overloaded governed functions prohibit gate 8D3-prime: {overloaded}")
    duplicated = sorted(key for key, entries in triggers.items() if len(entries) != 1)
    if duplicated:
        raise RuntimeError(f"duplicated governed triggers prohibit gate 8D3-prime: {duplicated}")
    for name in REPLACED_FUNCTIONS:
        if name not in functions:
            raise RuntimeError(f"gate 8D3-prime requires the installed {name}")
    if _installed_body(cursor, "market_validate_gate5_registration") != PRIOR_GATE5_PROSRC:
        raise RuntimeError("the installed gate5 registration validator is not the 0023 body")
    if _installed_body(cursor, "market_validate_discovery_seal_deferred") != PRIOR_SEAL_PROSRC:
        raise RuntimeError("the installed discovery seal validator is not the 0023 body")
    if SUCCESSOR_PLAN_SHA256 in PRIOR_GATE5_PROSRC or SUCCESSOR_PLAN_SHA256 in PRIOR_SEAL_PROSRC:
        raise RuntimeError("successor registration authority is already installed")
    return functions, triggers


def _untouched(catalog):
    functions, triggers = catalog
    return (
        {name: entries for name, entries in functions.items() if name not in REPLACED_FUNCTIONS},
        triggers,
    )


def _successor_authority_evidence(cursor):
    """Any downstream authority or evidence the successor plan has produced."""
    cursor.execute(
        """
        SELECT
          (SELECT count(*) FROM market_historicaldiscoveryplan p
            WHERE p.sha256=%s AND p.sealed_at IS NOT NULL)
        + (SELECT count(*) FROM market_historicaldiscoveryapproval ap
            JOIN market_historicaldiscoveryplan p ON p.id=ap.plan_id WHERE p.sha256=%s)
        + (SELECT count(*) FROM market_historicaldiscoveryregistration rg
            JOIN market_historicaldiscoveryplan p ON p.id=rg.plan_id WHERE p.sha256=%s)
        + (SELECT count(*) FROM market_historicaldiscoverysupersession s
            JOIN market_historicaldiscoveryplan p ON p.id=s.replacement_plan_id
           WHERE p.sha256=%s)
        """,
        [SUCCESSOR_PLAN_SHA256] * 4,
    )
    return bool(cursor.fetchone()[0])


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        before = _untouched(_preflight(cursor))
        _install(cursor, GATE5_SIGNATURE, "void", SUCCESSOR_GATE5_PROSRC)
        _install(cursor, SEAL_SIGNATURE, "trigger", SUCCESSOR_SEAL_PROSRC)
        if _installed_body(cursor, "market_validate_gate5_registration") != SUCCESSOR_GATE5_PROSRC:
            raise RuntimeError("gate 8D3-prime did not install the successor gate5 validator")
        if (
            _installed_body(cursor, "market_validate_discovery_seal_deferred")
            != SUCCESSOR_SEAL_PROSRC
        ):
            raise RuntimeError("gate 8D3-prime did not install the successor seal validator")
        if _untouched(_catalog(cursor)) != before:
            raise RuntimeError("gate 8D3-prime must not alter any other governance object")


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _successor_authority_evidence(cursor):
            raise RuntimeError(
                "successor discovery approval, registration, sealing or supersession evidence"
                " prohibits gate 8D3-prime reversal"
            )
        before = _untouched(_catalog(cursor))
        _install(cursor, GATE5_SIGNATURE, "void", PRIOR_GATE5_PROSRC)
        _install(cursor, SEAL_SIGNATURE, "trigger", PRIOR_SEAL_PROSRC)
        if _installed_body(cursor, "market_validate_gate5_registration") != PRIOR_GATE5_PROSRC:
            raise RuntimeError("gate 8D3-prime reversal did not restore the gate5 validator")
        if _installed_body(cursor, "market_validate_discovery_seal_deferred") != PRIOR_SEAL_PROSRC:
            raise RuntimeError("gate 8D3-prime reversal did not restore the seal validator")
        if _untouched(_catalog(cursor)) != before:
            raise RuntimeError("gate 8D3-prime reversal must not alter other governance")


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("market", "0023_gate8b_prime_successor_discovery_activation")]

    operations = [migrations.RunPython(forward, reverse)]
