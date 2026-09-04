# Failed-break v2 S0 preparation and acceptance boundary

This report covers code-only preparation from repository baseline
`db7a774c8e381b013a26aaa82d8ab3730b823bab`. It is not authority to run S0 on
the persistent research database, accept an S0 outcome, implement or execute
v2 S1, or access returns.

## Reuse determination

The existing S0 numerical projection depends on the registered dataset,
sealed H1/D/W membership, development partition, opening bid/ask spreads,
session classification, pipettes and warm-up convention. None depends on the
v1 detector's H1/D/W admission ordering or supporting-swing lifetime rule.
Because v2 retains the same registered dataset, development boundary, session
and spread methodology, and warm-up rule, all coverage, missingness, eligible
observation, spread-distribution, P99-ceiling, warm-up and cutoff values must
reproduce exactly.

The accepted v1 S0 `JobRun` cannot be reused. Its configuration, report,
idempotency key and acceptance artifact bind StrategyVersion 1,
`failed-break-phase-1-freeze-v1`, `failed-break-detector-v1` and the v1 content
hash. The provider-observed dataset contract and registration also preserve
that v1 strategy relationship as immutable data lineage; that relationship is
validated but is not treated as v2 authorization.

V2 therefore requires a new StrategyVersion and StrategyParameterManifest, a
new atomic S0 JobRun, and an independently reviewed post-execution acceptance
artifact. No schema migration or database-catalog change is required.

## Governed preparation

- Preregistration identity: `failed-break-v2-s0-preregistration-v1`.
- Preregistration self-hash:
  `336502cbdb8dbf9098891478b29ac90af39e7b7c1be3e02592edd2e2b36b984d`.
- Preregistration artifact SHA-256:
  `99b45b18b1345cd0d6f12863354e8aea7a39b62ab9b95651ed12db7836752d6f`.
- S0 methodology identity: `failed-break-return-blind-s0-v2`.
- Configuration identity: `failed-break-v2-s0-configuration-v1`.
- Report identity: `failed-break-v2-s0-report-v1`.
- Future outcome identity: `failed-break-v2-s0-outcome-acceptance-v1`.
- Strategy identity: `failed-break-phase-1-admission-correction-v2`.
- Detector identity: `failed-break-detector-v2-admission-correction`.
- Strategy content/detector artifact SHA-256:
  `3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861`.

The committed artifact is a preregistration only. The fixed outcome path is
absent and its loader pin is `None`; readiness therefore reports that persistent
S0 requires separate authorization and that v2 S1 remains unauthorized.

## Production-shaped disposable rehearsal

The accepted post-S1 backup SHA-256
`9b8bb6845fe1f8b9dcb0f340d13c0edfe09529564065095318781c89c7a677e0`
was restored into the collision-resistant disposable database
`failed_break_v2_s0_phase1_20260903_bN9WGQ` on a private Unix-socket-only
PostgreSQL cluster. Provider credentials were removed and external proxies were
set to the dead endpoint `127.0.0.1:9`.

The readiness command performed no writes. The `--execute` rehearsal ran once
in 18.74 seconds and created only:

- StrategyVersion 2;
- StrategyParameterManifest 2;
- JobRun 4, named `failed-break-signal-count-s0-v2`.

Its rehearsal-only configuration SHA-256 was
`d4a61a87ed54f3a479f05a81f83cb52a97c46a2b4bf6be5f5cc735462a56d1ba`
and report SHA-256 was
`cebaab3f8ff2157d0f40159f5d4e931d76a17edfc5237be54f39781cfefa424c`.
These are not accepted persistent identities.

An independent second derivation matched the preregistration and stored report
exactly. Compared with accepted v1 S0 JobRun 1, every numerical field was equal:

- eligible session observations: 201,101;
- all D/H1/W coverage counts;
- zero missingness;
- all 24 spread-distribution hashes;
- all six spread ceilings (`AUD_USD 0.00100`, `EUR_GBP 0.00100`,
  `EUR_USD 0.00100`, `GBP_USD 0.00150`, `USD_CAD 0.00100`,
  `USD_JPY 0.100`);
- all warm-up counts (D 279–290, H1 25 and W 1 per instrument);
- development contribution count and latest contribution timestamp.

Only the strategy/parameter/JobRun identity and resulting configuration/report
hashes changed. The restored 344,667 AnalysisRuns, 17,162 levels, 855 setups and
761 entry evaluations were unchanged. V1 JobRun 1 was refused as v2 evidence,
and the post-execution acceptance loader refused with
`v2 S0 has no committed post-execution outcome acceptance`.

No post-entry price, S1 evidence payload, outcome, return, provider, credential,
production database or persistent research database was accessed. The
disposable database and private cluster were removed after verification.

## Next prerequisite

Before a v2 S1 runner may be implemented, the exact persistent v2 S0 command
must be separately authorized and run once, its stored numerical evidence must
reconstruct, and a canonical post-execution outcome artifact must be committed
and independently accepted. V2 S1 execution would remain a separate authority.
