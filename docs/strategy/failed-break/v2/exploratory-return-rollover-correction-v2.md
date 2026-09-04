# V2 exploratory-return rollover selection correction

Status: forward-only code correction validated on disposable real data; persistent execution not yet performed.

## Consumed attempt

Authorization `d3c05c54a6fd0ec9af65f88489e30948f9ace072835756dd5c4b999f91de0b85` was consumed by one invocation. It exited 1 after 5.629354 seconds at `stage=calculation completed=0 total=82` with `missing or extra governed rollover`. The atomic transaction committed no row: the application-count hash remained `5b10daadf1f394681c3da0897bef1132bfb7fbf47bc7c5e8efca95758fce8097`, JobRuns remained five, and exploratory-result and idempotency rows remained zero.

## Complete diagnosis

The adapter preloads the exact frozen New York 17:00 weekday rollover sequence through every event's governed maximum horizon. The calculator instead compared that complete horizon preload with the shorter sequence through the resolved exit. This failed whenever a stop, target or daily-structure exit occurred before the horizon.

All 82 physical events were checked against the restored accepted evidence. Every supplied list matched the governed maximum-horizon sequence. Seventy-eight early-exit events had between two and eleven later horizon rollovers; four events had no difference. The exact extra-count distribution was `0:4, 2:1, 3:4, 4:1, 5:6, 6:12, 7:17, 8:6, 9:21, 10:8, 11:2`.

## Correction and policy preservation

The calculator now validates the complete horizon preload first, then applies only the validated prefix whose timestamp is less than or equal to the resolved exit. Exit equality remains inclusive. The frozen calendar remains 17:00 America/New_York, one day Monday/Tuesday/Thursday/Friday and three days Wednesday. Provider closures do not create synthetic candles; the existing sealed-evidence adapter supplies the latest qualifying evidence. Missing, extra, reordered or altered horizon evidence still fails closed.

No strategy or financial rule changed. The physical-event set, memberships, entry/stop/target geometry, terminal ordering, side-aware prices, conversion routes, commission-financing grid, risk rules, bootstrap, query architecture, atomic write and permanent non-promotion remain unchanged.

## Disposable real-data proof

The verified backup with SHA-256 `b80df86bc041cfaa1c954c6448d7a8dc30fe6037019140abd2a713d0b42802b9` was restored into two isolated disposable databases. Both complete 82-event calculations reached one atomic JobRun insert and exact readback, resolved all 82 events, and constructed all 3,690 event-risk-cost cells. Durations were 5.859597 and 5.955830 seconds. Both independently produced evidence hash `f3935a16dcd2d3e7e089b647f38f02f43913a4baae2dde11f2bd3e8ff099f920` and report hash `a27d92e9408382258210d7f1b1d0e8f4eacb10b75d6ff43975c25611998485d9`.

These hashes prove deterministic correction behaviour; they are not profitability gates and did not alter any policy or threshold. No persistent research or production row was changed during diagnosis or rehearsal.
