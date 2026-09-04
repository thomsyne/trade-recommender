# V2 exploratory-return macOS memory-boundary correction

## Accepted failure and diagnosis

The first authorization is consumed. Its single invocation exited `1` in 1.09 seconds with peak RSS 78,053,376 bytes before outcome loading, calculation, transaction entry, or persistence. The total SQL query count was not instrumented and remains unknown. Persistent application state stayed at count hash `5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097`, with zero result and idempotency rows.

The native arm64 `.venv/bin/python` reports `resource.RLIM_INFINITY` and both `RLIMIT_AS` limits as `9223372036854775807`. The failed code requested `(1073741824, 9223372036854775807)`. A database-free subprocess reproduced `ValueError: current limit exceeds maximum limit`. Direct Darwin `setrlimit(2)` probes also rejected finite-soft/infinite-hard and finite-soft/finite-hard `RLIMIT_AS` tuples with `EINVAL`; a 256 MiB allocation remained possible after the rejected 64 MiB request. Darwin aliases `RLIMIT_RSS` to `RLIMIT_AS`. The problem is therefore not ordinary `-1` infinity ordering, a soft-greater-than-hard tuple, restoration, or an attempted hard-limit increase: finite `RLIMIT_AS` is not an enforceable boundary for this macOS 26.5.2 universal2/arm64 runtime.

## Corrected boundary

The exact command, calculator, adapter, financial semantics, 82-event cohort, 186 memberships, policy, result format, schema, and idempotency key are unchanged. The command now starts one isolated worker only after fixed-path successor authorization and host RSS monitoring succeed. The worker owns outcome loading and the one atomic PostgreSQL transaction. Its parent samples resident memory every 50 ms using Darwin `proc_pid_rusage` (or Linux `/proc/<pid>/statm`), enforces 1,073,741,824 bytes and a monotonic 900-second ceiling, and emits only count/stage progress. A breach or timeout terminates the worker; closing its database connection rolls the transaction back. No partial result crosses the process boundary.

The parent never changes `RLIMIT_AS`, never raises or loosens an existing limit, and derives the effective ceiling as the strictest finite value among the authorized cap and any pre-existing finite soft/hard limits. Infinity is tested by equality with `RLIM_INFINITY`, never by integer ordering. The original resource tuple, signal handler, and interval timer are verified/restored in `finally`; setup, sampling, worker, memory, timeout, and restoration failures become governed refusals.

The database-free host smoke test entered and exited `_operational_limits()` under native arm64 `.venv/bin/python`, sampled positive RSS, and preserved the original `(9223372036854775807, 9223372036854775807)` tuple and timer/signal state exactly.

## Forward-only governance

- Original authorization artifact: `21c2a3ce7a8ae7eb46ca07a551160a1830f58b4938215491ab40d026f96c349c` (immutable, consumed, cannot authorize again).
- Accepted failure artifact: `47f76090cd933002067d3f48594c8fcd68fdb6e48d2f121089212b20ebd910b0`; self-hash `7a76a6c0249f9f5d5eece84f90175880d712624ed1c79eb7a4821ab1b4d8030e`.
- Successor replacement authorization: `e84b1b4b4a8b6b6c25ff4eefca21ab649b4a460a0b3db04b09c0433888407868`; self-hash `d6b3e312f80a8395418726e95e384463c29feb11352e0306e46f9398c5f833a5`.
- Corrected runner source: `11f8d31684f7306b2ba4aed2715eb404e982c1e63875f0dc8cb2fc6d487eeeb2`.
- Memory-boundary source: `7e39e860419e677a811ad7fe755747c81d1ba4d8be329a1cbdfdf09f2bb8a182`.
- Updated preregistration artifact: `3e465e56af7eb0bc5eef175618dc8c38d0e8fafcc7a867d6b31e70946de3a93a`; self-hash `b8877148c25b8982867e3df77314142b4b0d18924d820ea7777275292de4fca7`.

The successor authorizes exactly one replacement invocation and requires a new verified pre-operation backup. Any further retry, resume, replacement, promotion, or live trading requires new forward-only governance or remains permanently prohibited as applicable.

## Synthetic rehearsal

The disposable database contained only a minimal synthetic `research_jobrun` table and was removed after confirming zero active sessions. One successful run committed one JobRun in 0.160187 seconds with worker peak RSS 38,174,720 bytes and exactly one duplicate check, insert, and readback query. Every other application-table delta was zero. Injected post-insert failure, watchdog timeout, and memory breach each left zero rows. Concurrent invocations produced one commit and one UNIQUE-constraint refusal; repeat execution refused. A favourable synthetic payload could not enable promotion.

Rehearsal artifact SHA: `8b1e433337856f2b85d2ff26dc9f2d943879a126272599298cdff43ce11796a7`; self-hash `97351aa03080b7903cbb152ee250a1d945f0963979298f85f69ef2d199f2f10b`.

## Persistent readiness boundary

The post-correction persistent check ran strictly return-blind and read-only. It reported `AUTHORIZED_NOT_EXECUTED`, 82 events, zero outcome queries, and zero writes while preserving application-count hash `5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097` and zero result/idempotency rows. No real `--execute` command was invoked as part of this correction.
