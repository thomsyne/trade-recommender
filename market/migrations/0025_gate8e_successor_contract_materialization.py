"""Gate 8E: successor contract and acquisition-plan materialization authority.

The installed 0024 catalog refuses a successor data contract: three validators
pin predecessor-only literals. This migration adds the smallest successor-scoped
branch to each and changes nothing else.

  market_validate_data_contract        contract insert
  market_validate_replacement_plan     acquisition plan insert (via
                                       market_validate_historical_plan)
  market_validate_acquisition_canary   acquisition attempt admission (via
                                       market_validate_historical_attempt) --
                                       the Gate 8F restriction, installed now
                                       and fail-closed, authorizing nothing

Every predecessor comparison survives verbatim in the ELSE arm of a generation
CASE, so the v2 generation validates exactly as it did under 0024. Each successor
branch is keyed on the successor data identity and pins the independently
accepted Gate 8D3/8D4 evidence; a row carrying the successor identity without
that evidence is refused here rather than falling through to predecessor
behaviour.

Semantic note: the successor contract payload retains
``discovery_version = 'phase-2b1r-discovery-v1'``. That field names the discovery
contract generation, which is unchanged, not the discovery plan generation. The
predecessor is the governing precedent: its contract carries the same value while
its discovery plan is v2. The successor is distinguished instead by its accepted
plan, manifest, semantic, operational, approval, registration and artifact
digests, and by its own data identity.

The generic validators are untouched: market_validate_historical_dataset,
market_validate_replacement_dataset, market_validate_historical_chunk,
market_validate_replacement_chunk and market_validate_historical_attempt contain
no generation-specific literal and require none.
"""

from importlib import import_module

from django.db import migrations

SUCCESSOR_DATA_IDENTITY = "oanda-ba-ny17-friday-provider-observed-v2"
SUCCESSOR_DISCOVERY_PLAN_SHA256 = "e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88"
SUCCESSOR_CONTRACT_SHA256 = "d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c"
SUCCESSOR_ACQUISITION_PLAN_SHA256 = (
    "44dc82b2f20975e34e34e30ca7a709fff059ed14fa7457aaa26da4222d4df4cd"
)
SUCCESSOR_DATASET_MANIFEST_SHA256 = (
    "11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014"
)
SUCCESSOR_ACQUISITION_CANARY_LOGICAL_KEY = (
    "7b96484393a7e82eafd3bb5389dbf7f6b5b00ba6c9ed201d81814829b44a6151"
)
SUCCESSOR_CHUNK_COUNT = 132

REQUIRED_FUNCTION_COUNT = 56
REQUIRED_TRIGGER_COUNT = 74

CONTRACT_SIGNATURE = "market_validate_data_contract()"
PLAN_SIGNATURE = "market_validate_replacement_plan(plan market_historicaldatasetplan)"
CANARY_SIGNATURE = (
    "market_validate_acquisition_canary(attempt_chunk_id bigint,"
    " new_attempt_number integer, new_idempotency_key text, new_run_id bigint)"
)
REPLACED_FUNCTIONS = (
    "market_validate_data_contract",
    "market_validate_replacement_plan",
    "market_validate_acquisition_canary",
)

PRIOR_CONTRACT_PROSRC = r"""
        DECLARE registration record; approval record; strategy record; expected_payload jsonb;
        BEGIN
          SELECT r.*, p.sha256 AS discovery_plan_sha256, p.sealed_at AS plan_sealed_at
            INTO STRICT registration
            FROM market_historicaldiscoveryregistration r
            JOIN market_historicaldiscoveryplan p ON p.id=r.plan_id
            WHERE r.id=NEW.discovery_registration_id;
          SELECT * INTO STRICT approval FROM market_historicaldiscoveryapproval
            WHERE id=registration.approval_id;
          SELECT * INTO STRICT strategy FROM research_strategyversion
            WHERE id=NEW.strategy_version_id;
          expected_payload := jsonb_build_object(
            'discovery_contract','oanda-provider-observed-timestamp-discovery',
            'discovery_version','phase-2b1r-discovery-v1',
            'source_identity','oanda-v20-market-candles-v1',
            'phase1_spec_hash','47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd',
            'phase1_manifest_hash','f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882',
            'replacement_data_identity','oanda-ba-ny17-friday-provider-observed-v1',
            'superseded_semantic_identity','oanda-ba-ny17-friday-v1',
            'global_semantic_inventory_sha256',NEW.global_semantic_inventory_sha256);
          IF NEW.identity<>'oanda-ba-ny17-friday-provider-observed-v1'
             OR NEW.superseded_data_identity<>'oanda-ba-ny17-friday-v1'
             OR NEW.phase1_spec_hash<>'47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash<>'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR registration.plan_sealed_at IS NULL
             OR registration.plan_sealed_at<>registration.registered_at
             OR registration.discovery_plan_sha256<>'2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
             OR NEW.global_semantic_inventory_sha256
                <>registration.global_semantic_inventory_sha256
             OR NEW.approval_sha256<>approval.sha256
             OR NEW.registration_report_sha256<>registration.report_sha256
             OR strategy.content_hash<>NEW.phase1_manifest_hash
             OR strategy.data_identity<>NEW.superseded_data_identity
             OR NEW.payload<>expected_payload
             OR NEW.sha256<>market_sha256(expected_payload)
          THEN RAISE EXCEPTION 'historical data contract lineage does not reconstruct'; END IF;
          RETURN NEW;
        END"""

SUCCESSOR_CONTRACT_PROSRC = r"""
        DECLARE registration record; approval record; strategy record; expected_payload jsonb;
        BEGIN
          IF NEW.identity NOT IN ('oanda-ba-ny17-friday-provider-observed-v1','oanda-ba-ny17-friday-provider-observed-v2') THEN
            RAISE EXCEPTION 'historical data contract lineage does not reconstruct';
          END IF;
          SELECT r.*, p.sha256 AS discovery_plan_sha256, p.sealed_at AS plan_sealed_at
            INTO STRICT registration
            FROM market_historicaldiscoveryregistration r
            JOIN market_historicaldiscoveryplan p ON p.id=r.plan_id
            WHERE r.id=NEW.discovery_registration_id;
          SELECT * INTO STRICT approval FROM market_historicaldiscoveryapproval
            WHERE id=registration.approval_id;
          SELECT * INTO STRICT strategy FROM research_strategyversion
            WHERE id=NEW.strategy_version_id;
          expected_payload := jsonb_build_object(
            'discovery_contract','oanda-provider-observed-timestamp-discovery',
            'discovery_version','phase-2b1r-discovery-v1',
            'source_identity','oanda-v20-market-candles-v1',
            'phase1_spec_hash','47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd',
            'phase1_manifest_hash','f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882',
            'replacement_data_identity',NEW.identity,
            'superseded_semantic_identity','oanda-ba-ny17-friday-v1',
            'global_semantic_inventory_sha256',NEW.global_semantic_inventory_sha256);
          IF FALSE
             OR NEW.superseded_data_identity<>'oanda-ba-ny17-friday-v1'
             OR NEW.phase1_spec_hash<>'47d0346bcf723cb78a71763df43f6b092b0c235bb1d17ccbe69f17d9550203cd'
             OR NEW.phase1_manifest_hash<>'f857dd9155646093616af0d87e534552540752541f2cb33a6ce3e3c68af0b882'
             OR registration.plan_sealed_at IS NULL
             OR registration.plan_sealed_at<>registration.registered_at
             OR registration.discovery_plan_sha256<>(CASE WHEN NEW.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88' ELSE '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a' END)
             OR NEW.global_semantic_inventory_sha256
                <>registration.global_semantic_inventory_sha256
             OR NEW.approval_sha256<>approval.sha256
             OR NEW.registration_report_sha256<>registration.report_sha256
             OR strategy.content_hash<>NEW.phase1_manifest_hash
             OR strategy.data_identity<>NEW.superseded_data_identity
             OR NEW.payload<>expected_payload
             OR NEW.sha256<>market_sha256(expected_payload)
             OR (NEW.identity='oanda-ba-ny17-friday-provider-observed-v2' AND (
                  NEW.sha256<>'d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c'
               OR NEW.global_semantic_inventory_sha256<>'f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427'
               OR NEW.approval_sha256<>'e66b24df552cd09b88bb0249312b2263a280d7e40fd4b2d6b5d955703ae3a08c'
               OR NEW.registration_report_sha256<>'5ac48c97817adce8687ae35717811a7a1bbc94dbfc8a12a0575849ea53d2a8ca'
               OR registration.ordered_chunk_manifest_sha256<>'6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0'
               OR registration.accepted_operational_evidence_set_sha256<>'5653e5be68d47d793ae68e774467a2fdb5b06edd60e6adecbf7c02fd2697235b'
               OR registration.cross_series_report_sha256<>'b13fe357e5c2dec3450a6fc15cf755d6a940e6b83af8592cfdedaa9cc74156c5'))
          THEN RAISE EXCEPTION 'historical data contract lineage does not reconstruct'; END IF;
          RETURN NEW;
        END"""

PRIOR_PLAN_PROSRC = r"""
        DECLARE contract record; strategy record; discovery record; mismatched integer;
                request_count integer; discovery_chunks integer; total_expected bigint;
                inventory_total bigint;
        BEGIN
          SELECT * INTO STRICT contract FROM market_historicaldatacontract
            WHERE id=plan.data_contract_id;
          SELECT r.plan_id AS discovery_plan_id, p.sha256 AS discovery_plan_sha,
                 p.sealed_at
            INTO STRICT discovery
            FROM market_historicaldiscoveryregistration r
            JOIN market_historicaldiscoveryplan p ON p.id=r.plan_id
            WHERE r.id=contract.discovery_registration_id;
          SELECT v.* INTO STRICT strategy FROM research_strategyversion v
            WHERE v.id=plan.strategy_version_id;
          IF plan.identity<>contract.identity
             OR plan.data_contract_sha256<>contract.sha256
             OR contract.strategy_version_id<>plan.strategy_version_id
             OR discovery.sealed_at IS NULL
             OR discovery.discovery_plan_sha<>'2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a'
             OR plan.phase1_spec_hash<>contract.phase1_spec_hash
             OR plan.phase1_manifest_hash<>contract.phase1_manifest_hash
             OR strategy.content_hash<>contract.phase1_manifest_hash
             OR strategy.data_identity<>contract.superseded_data_identity
             OR plan.instruments<>'["AUD_USD","EUR_GBP","EUR_USD","GBP_USD","USD_CAD","USD_JPY"]'::jsonb
             OR plan.granularities<>'["D","H1","W"]'::jsonb
             OR plan.alignment<>'{"timezone":"America/New_York","daily_hour":17,"weekly_day":"Friday","smooth":false}'::jsonb
             OR plan.price_component<>'COMBINED_BID_ASK' OR NOT plan.complete_only
             OR plan.payload->>'acquisition_contract'<>'failed-break-provider-observed-historical-acquisition'
             OR plan.payload->>'acquisition_version'<>'phase-2b1r-v1'
             OR plan.payload->>'data_identity'<>contract.identity
             OR plan.payload->>'data_contract_sha256'<>contract.sha256
             OR plan.payload->>'discovery_plan_sha256'<>discovery.discovery_plan_sha
             OR plan.payload->'strategy'->>'content_hash'<>strategy.content_hash
             OR plan.payload->>'phase1_spec_hash'<>plan.phase1_spec_hash
             OR plan.payload->>'phase1_manifest_hash'<>plan.phase1_manifest_hash
             OR plan.sha256<>market_sha256(plan.payload)
          THEN RAISE EXCEPTION
            'replacement plan conflicts with the data contract'; END IF;
          SELECT count(*) INTO discovery_chunks FROM market_historicaldiscoverychunk c
            WHERE c.plan_id=discovery.discovery_plan_id;
          SELECT count(*), coalesce(sum((request->>'expected_observation_count')::integer),0)
            INTO request_count, total_expected
            FROM jsonb_array_elements(plan.payload->'requests') AS request;
          SELECT count(*) INTO mismatched
            FROM jsonb_array_elements(plan.payload->'requests') AS request
            LEFT JOIN market_historicaldiscoverychunk c
              ON c.plan_id=discovery.discovery_plan_id
             AND c.ordinal=(request->>'ordinal')::integer
            LEFT JOIN market_historicaltimestampinventory i ON i.chunk_id=c.id
            LEFT JOIN market_instrument ins ON ins.id=c.instrument_id
            WHERE c.id IS NULL OR i.id IS NULL
               OR request->'canonical_request' IS DISTINCT FROM c.canonical_request
               OR request->>'canonical_request_sha256'
                  IS DISTINCT FROM c.canonical_request_sha256
               OR request->>'semantic_inventory_sha256'
                  IS DISTINCT FROM i.semantic_inventory_sha256
               OR (request->>'expected_observation_count')::integer
                  IS DISTINCT FROM i.observation_count
               OR request->>'instrument' IS DISTINCT FROM ins.code
               OR request->>'granularity' IS DISTINCT FROM c.granularity;
          SELECT coalesce(sum(i.observation_count),0) INTO inventory_total
            FROM market_historicaltimestampinventory i
            JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
            WHERE c.plan_id=discovery.discovery_plan_id;
          IF request_count<>discovery_chunks OR mismatched<>0
             OR total_expected<>inventory_total
             OR (plan.payload->>'expected_total_observations')::bigint<>inventory_total
          THEN RAISE EXCEPTION
            'replacement plan does not reconstruct the sealed inventory'; END IF;
        END"""

SUCCESSOR_PLAN_PROSRC = r"""
        DECLARE contract record; strategy record; discovery record; mismatched integer;
                request_count integer; discovery_chunks integer; total_expected bigint;
                inventory_total bigint;
        BEGIN
          SELECT * INTO STRICT contract FROM market_historicaldatacontract
            WHERE id=plan.data_contract_id;
          SELECT r.plan_id AS discovery_plan_id, p.sha256 AS discovery_plan_sha,
                 p.sealed_at
            INTO STRICT discovery
            FROM market_historicaldiscoveryregistration r
            JOIN market_historicaldiscoveryplan p ON p.id=r.plan_id
            WHERE r.id=contract.discovery_registration_id;
          SELECT v.* INTO STRICT strategy FROM research_strategyversion v
            WHERE v.id=plan.strategy_version_id;
          IF plan.identity<>contract.identity
             OR plan.data_contract_sha256<>contract.sha256
             OR contract.strategy_version_id<>plan.strategy_version_id
             OR discovery.sealed_at IS NULL
             OR discovery.discovery_plan_sha<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88' ELSE '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a' END)
             OR plan.phase1_spec_hash<>contract.phase1_spec_hash
             OR plan.phase1_manifest_hash<>contract.phase1_manifest_hash
             OR strategy.content_hash<>contract.phase1_manifest_hash
             OR strategy.data_identity<>contract.superseded_data_identity
             OR plan.instruments<>'["AUD_USD","EUR_GBP","EUR_USD","GBP_USD","USD_CAD","USD_JPY"]'::jsonb
             OR plan.granularities<>'["D","H1","W"]'::jsonb
             OR plan.alignment<>'{"timezone":"America/New_York","daily_hour":17,"weekly_day":"Friday","smooth":false}'::jsonb
             OR plan.price_component<>'COMBINED_BID_ASK' OR NOT plan.complete_only
             OR plan.payload->>'acquisition_contract'<>'failed-break-provider-observed-historical-acquisition'
             OR plan.payload->>'acquisition_version'<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'phase-2b1r-v2' ELSE 'phase-2b1r-v1' END)
             OR plan.payload->>'data_identity'<>contract.identity
             OR plan.payload->>'data_contract_sha256'<>contract.sha256
             OR plan.payload->>'discovery_plan_sha256'<>discovery.discovery_plan_sha
             OR plan.payload->'strategy'->>'content_hash'<>strategy.content_hash
             OR plan.payload->>'phase1_spec_hash'<>plan.phase1_spec_hash
             OR plan.payload->>'phase1_manifest_hash'<>plan.phase1_manifest_hash
             OR plan.sha256<>market_sha256(plan.payload)
             OR (contract.identity='oanda-ba-ny17-friday-provider-observed-v2' AND (
                  contract.sha256<>'d630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c'
               OR plan.sha256<>'44dc82b2f20975e34e34e30ca7a709fff059ed14fa7457aaa26da4222d4df4cd'))
          THEN RAISE EXCEPTION
            'replacement plan conflicts with the data contract'; END IF;
          SELECT count(*) INTO discovery_chunks FROM market_historicaldiscoverychunk c
            WHERE c.plan_id=discovery.discovery_plan_id;
          SELECT count(*), coalesce(sum((request->>'expected_observation_count')::integer),0)
            INTO request_count, total_expected
            FROM jsonb_array_elements(plan.payload->'requests') AS request;
          SELECT count(*) INTO mismatched
            FROM jsonb_array_elements(plan.payload->'requests') AS request
            LEFT JOIN market_historicaldiscoverychunk c
              ON c.plan_id=discovery.discovery_plan_id
             AND c.ordinal=(request->>'ordinal')::integer
            LEFT JOIN market_historicaltimestampinventory i ON i.chunk_id=c.id
            LEFT JOIN market_instrument ins ON ins.id=c.instrument_id
            WHERE c.id IS NULL OR i.id IS NULL
               OR request->'canonical_request' IS DISTINCT FROM c.canonical_request
               OR request->>'canonical_request_sha256'
                  IS DISTINCT FROM c.canonical_request_sha256
               OR request->>'semantic_inventory_sha256'
                  IS DISTINCT FROM i.semantic_inventory_sha256
               OR (request->>'expected_observation_count')::integer
                  IS DISTINCT FROM i.observation_count
               OR request->>'instrument' IS DISTINCT FROM ins.code
               OR request->>'granularity' IS DISTINCT FROM c.granularity;
          SELECT coalesce(sum(i.observation_count),0) INTO inventory_total
            FROM market_historicaltimestampinventory i
            JOIN market_historicaldiscoverychunk c ON c.id=i.chunk_id
            WHERE c.plan_id=discovery.discovery_plan_id;
          IF request_count<>discovery_chunks OR mismatched<>0
             OR total_expected<>inventory_total
             OR (plan.payload->>'expected_total_observations')::bigint<>inventory_total
          THEN RAISE EXCEPTION
            'replacement plan does not reconstruct the sealed inventory'; END IF;
        END"""

PRIOR_CANARY_PROSRC = r"""
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

SUCCESSOR_CANARY_PROSRC = r"""
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
          IF contract.sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'd630cc100cd06abdaa5d08d88353542999d625dd0c80f43eecbb5f649109f11c' ELSE '60b603f26662bfc8faa4373177690bc0ae23820b914815f47c11d8367c07f7bf' END)
             OR market_sha256(contract.payload)<>contract.sha256
             OR contract.identity NOT IN ('oanda-ba-ny17-friday-provider-observed-v1','oanda-ba-ny17-friday-provider-observed-v2')
             OR contract.global_semantic_inventory_sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'f0285221956d4ec2d802eba1dc80f5a6d2a7be6697e62b1b3782705886b69427' ELSE '78f8559bc9b14e84f8c1b1002d30ddd77d1918e9c026812b5ce6e2b0ca8af02c' END)
             OR contract.approval_sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'e66b24df552cd09b88bb0249312b2263a280d7e40fd4b2d6b5d955703ae3a08c' ELSE '41d3d0cc97c82882fd56fd1459b71df862f76d2e4c698eb759df1a82a0f25586' END)
             OR contract.approval_sha256<>approval.sha256
             OR contract.registration_report_sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN '5ac48c97817adce8687ae35717811a7a1bbc94dbfc8a12a0575849ea53d2a8ca' ELSE 'cd0acdcb52aa0a321aed3ecbb4a7f9edc38fa8d31444c5bbc2927fefd9154844' END)
             OR contract.registration_report_sha256<>registration.report_sha256
             OR registration.plan_sealed_at IS NULL
             OR registration.plan_sealed_at<>registration.registered_at
             OR registration.discovery_plan_sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN 'e35d669efa860dd44e5fc145a65aaeabcd0d8745df5718507fa2b1a38abb3f88' ELSE '2a25bbc28fca5d596b26d3d2921fa881e374174fb08cc1dbfb51e47c8b138e3a' END)
             OR registration.ordered_chunk_manifest_sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN '6d31a7aee0866c1e4b2479a78816594769005eaa759714c93dea39d55fddbea0' ELSE '04835164d5c2abe633efd1a8ddc58edcc7c9d5e8347c01425df5049d9b74b427' END)
             OR registration.global_semantic_inventory_sha256<>
                contract.global_semantic_inventory_sha256
             OR plan.sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN '44dc82b2f20975e34e34e30ca7a709fff059ed14fa7457aaa26da4222d4df4cd' ELSE 'f0be516c732d775ce57fd98a39a7dd7df917d4eaa2c9c0ffd2fc7028d9a23528' END)
             OR market_sha256(plan.payload)<>plan.sha256
             OR plan.data_contract_sha256<>contract.sha256
             OR dataset.manifest_sha256<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN '11da094fc7ca6a30e946be33523757d7ab559a9ad1951c9142e8969539930014' ELSE '9c1c18043dfaf1f36b04fd132c07ec3349c3506828a6799d83faa622b7c2aa54' END)
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
          IF chunk.logical_key<>(CASE WHEN contract.identity='oanda-ba-ny17-friday-provider-observed-v2' THEN '7b96484393a7e82eafd3bb5389dbf7f6b5b00ba6c9ed201d81814829b44a6151' ELSE 'e0a19ed9db1707420233af059f7c9f8d84fe87afe1ad59e7ab2e8b195121fd3c' END) THEN
            PERFORM market_verify_replacement_canary_success();
          END IF;
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


def _untouched(catalog):
    functions, triggers = catalog
    return (
        {name: entries for name, entries in functions.items() if name not in REPLACED_FUNCTIONS},
        triggers,
    )


def _preflight(cursor):
    """The complete installed 0024 catalog, or nothing happens."""
    functions, triggers = _catalog(cursor)
    if len(functions) != REQUIRED_FUNCTION_COUNT:
        raise RuntimeError(
            f"gate 8E requires the {REQUIRED_FUNCTION_COUNT}-function 0024 catalog,"
            f" found {len(functions)}"
        )
    if len(triggers) != REQUIRED_TRIGGER_COUNT:
        raise RuntimeError(
            f"gate 8E requires the {REQUIRED_TRIGGER_COUNT}-trigger 0024 catalog,"
            f" found {len(triggers)}"
        )
    overloaded = sorted(name for name, entries in functions.items() if len(entries) != 1)
    if overloaded:
        raise RuntimeError(f"overloaded governed functions prohibit gate 8E: {overloaded}")
    duplicated = sorted(key for key, entries in triggers.items() if len(entries) != 1)
    if duplicated:
        raise RuntimeError(f"duplicated governed triggers prohibit gate 8E: {duplicated}")
    for name in REPLACED_FUNCTIONS:
        if name not in functions:
            raise RuntimeError(f"gate 8E requires the installed {name}")
    if _installed_body(cursor, "market_validate_data_contract") != PRIOR_CONTRACT_PROSRC:
        raise RuntimeError("the installed data contract validator is not the 0024 body")
    if _installed_body(cursor, "market_validate_replacement_plan") != PRIOR_PLAN_PROSRC:
        raise RuntimeError("the installed replacement plan validator is not the 0024 body")
    if _installed_body(cursor, "market_validate_acquisition_canary") != PRIOR_CANARY_PROSRC:
        raise RuntimeError("the installed acquisition canary validator is not the 0024 body")
    if SUCCESSOR_DATA_IDENTITY in (PRIOR_CONTRACT_PROSRC + PRIOR_PLAN_PROSRC + PRIOR_CANARY_PROSRC):
        raise RuntimeError("successor acquisition authority is already installed")
    return functions, triggers


def _successor_gate8e_evidence(cursor):
    """Any successor Gate 8E metadata or acquisition evidence."""
    cursor.execute(
        """
        SELECT
          (SELECT count(*) FROM market_historicaldatacontract WHERE identity=%s)
        + (SELECT count(*) FROM market_historicaldatasetplan WHERE identity=%s)
        + (SELECT count(*) FROM market_historicalingestionchunk c
            JOIN market_historicaldatasetplan p ON p.id=c.plan_id WHERE p.identity=%s)
        + (SELECT count(*) FROM market_historicalingestionattempt a
            JOIN market_historicalingestionchunk c ON c.id=a.chunk_id
            JOIN market_historicaldatasetplan p ON p.id=c.plan_id WHERE p.identity=%s)
        """,
        [SUCCESSOR_DATA_IDENTITY] * 4,
    )
    return bool(cursor.fetchone()[0])


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        before = _untouched(_preflight(cursor))
        _install(cursor, CONTRACT_SIGNATURE, "trigger", SUCCESSOR_CONTRACT_PROSRC)
        _install(cursor, PLAN_SIGNATURE, "void", SUCCESSOR_PLAN_PROSRC)
        _install(cursor, CANARY_SIGNATURE, "void", SUCCESSOR_CANARY_PROSRC)
        if _installed_body(cursor, "market_validate_data_contract") != SUCCESSOR_CONTRACT_PROSRC:
            raise RuntimeError("gate 8E did not install the successor contract validator")
        if _installed_body(cursor, "market_validate_replacement_plan") != SUCCESSOR_PLAN_PROSRC:
            raise RuntimeError("gate 8E did not install the successor plan validator")
        if _installed_body(cursor, "market_validate_acquisition_canary") != SUCCESSOR_CANARY_PROSRC:
            raise RuntimeError("gate 8E did not install the successor canary validator")
        if _untouched(_catalog(cursor)) != before:
            raise RuntimeError("gate 8E must not alter any other governance object")


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _successor_gate8e_evidence(cursor):
            raise RuntimeError(
                "successor gate 8E metadata or acquisition evidence prohibits reversal"
            )
        before = _untouched(_catalog(cursor))
        _install(cursor, CONTRACT_SIGNATURE, "trigger", PRIOR_CONTRACT_PROSRC)
        _install(cursor, PLAN_SIGNATURE, "void", PRIOR_PLAN_PROSRC)
        _install(cursor, CANARY_SIGNATURE, "void", PRIOR_CANARY_PROSRC)
        if _installed_body(cursor, "market_validate_data_contract") != PRIOR_CONTRACT_PROSRC:
            raise RuntimeError("gate 8E reversal did not restore the contract validator")
        if _installed_body(cursor, "market_validate_replacement_plan") != PRIOR_PLAN_PROSRC:
            raise RuntimeError("gate 8E reversal did not restore the plan validator")
        if _installed_body(cursor, "market_validate_acquisition_canary") != PRIOR_CANARY_PROSRC:
            raise RuntimeError("gate 8E reversal did not restore the canary validator")
        if _untouched(_catalog(cursor)) != before:
            raise RuntimeError("gate 8E reversal must not alter other governance")


class Migration(migrations.Migration):
    atomic = True

    dependencies = [("market", "0024_gate8d3_prime_successor_registration_authority")]

    operations = [migrations.RunPython(forward, reverse)]
