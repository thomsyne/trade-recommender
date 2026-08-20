# Governed recommendation contract v3

This contract permits one bounded model assessment of an immutable
`PairEvidenceSnapshot`. It does not authorize broker access, order placement,
portfolio sizing, silent source reweighting, or historical sentiment replay.

## Input boundary

The provider receives rights-cleared macro, event, and news records plus
non-reconstructable local technical labels. OANDA prices, candle identifiers,
numeric technicals, reference midpoint, neutral-band value, and setup levels
are withheld. It cannot browse or call tools. News text is explicitly untrusted
data, and news not marked eligible for model processing is excluded.

Generation fails closed when the packet is more than eight hours old, its H4
market/technical inputs exceed 12 weekday hours, fixture market data is present,
the evidence schema/boundary is invalid, the API key is missing, or a spend
limit would be crossed.

## Output boundary

Claude uses constrained JSON Schema output. The application independently
validates:

- `buy`, `sell`, or explicit `abstain`;
- integer up/neutral/down probabilities summing to 100;
- summary plus separate technical, macro, and sentiment cases;
- at least one risk and citations to supplied evidence IDs only;
- `none`/`null` for all model-authored entry fields;
- at least one technical and one non-technical citation for a setup.

For a directional response, deterministic local policy v1 attaches the current
local midpoint as conditional entry and bounded local support/resistance as
invalidation/target. The model cannot author or override these numeric fields.

Malformed or semantically invalid output creates no recommendation. There is no
repair prompt in this contract: failure is visible without letting the model
negotiate the contract.

## Immutable audit record

`Recommendation` stores the exact transformed input packet, full
prompt/schema/model/request SHA-256,
source snapshot, provider/model/contract version, provider response ID, token
counts, calculated API cost, validated output, information cutoff, frozen daily
reference candle/midpoint/neutral band, and optional mechanical tactical control.
Django and PostgreSQL both reject updates and deletes. Re-running one
provider/model against the same evidence and reference is idempotent.

The model recommendation and mechanical forecast remain separate records. A
recommendation cannot mutate evidence, replace the control, or count as an
executed trade.

## Prospective resolution and calibration

Versions 2 and 3 define up, neutral, and down against the midpoint close of the fifth
subsequently completed OANDA daily candle. The neutral band is frozen at issue
time as the greater of 0.25 × daily ATR(14) and 2 × closing spread. Equality is
neutral. `RecommendationResolution` immutably stores the endpoint, outcome,
multiclass Brier score, and directional hit or miss. Abstentions receive a Brier
score but no directional hit label.

Version 1 recommendations are deliberately excluded: their confidence number
did not identify a precise event, so retroactive interpretation would create
false calibration. The current dashboard still has a provisional raw-30
display threshold. It is descriptive only and must be replaced by the
dependence-aware experiment-health slice before any reportability or skill
claim.

## Paper setup lifecycle

Directional version 3 setups begin with an immutable `pending` lifecycle event.
Versions 2 and 3 are monitored only against completed hourly OANDA
bid/ask candles whose intervals start after recommendation generation. Buys
enter on ask and exit on bid; sells enter on bid and exit on ask. Limit fills do
not receive favorable price improvement, adverse stop gaps use the opening
executable quote, and target/invalidation fills use their declared levels.

When target and invalidation coexist in one hourly candle, invalidation takes
precedence. A target touched in the same intrabar entry candle is ignored unless
the entry condition already held at that candle's open. Open setups expire at
the executable close of the fifth broker daily session. Immutable
`PaperTradeEntry` and `PaperTradeResult` records store the evidence candles,
spread, fill prices, gross pips, R-multiple, and policy details.
Explicit immutable lifecycle events distinguish pending, entered, closed,
legacy-unadjudicated, expired-unobserved, cancelled, and missing-data states.

These are paper observations, not orders. Gross pips embed bid/ask execution but
exclude financing, commission, sizing, leverage, and taxes. They are reported
separately from probabilistic thesis calibration and remain insufficient-sample
until 30 activated setups resolve.

## Currency exposure guardrails

Every unresolved directional supported setup is decomposed deterministically:
buying BASE/QUOTE is long base and short quote; selling it is short base and
long quote. Waiting entries remain included because they can still activate,
while abstentions, legacy recommendations, and completed paper setups are
excluded. Entered and waiting states remain visibly distinct.

The Exposure page reports gross and net setup equivalents, repeated
same-direction currency factors, and opposing factors. Position sizing policy
`fixed-cad-risk-v1` uses a declared C$25,000 model portfolio and risks at most
0.5% (C$125) from conditional entry to invalidation. Whole units are floored
after converting quote-currency risk into CAD through hourly candles that were
available when the immutable sizing record was created. The aggregate
unresolved cap is C$500 and the same-direction currency-factor cap is C$250.
Waiting setups count against both because they may activate.

This is direct factor accounting, not an estimated pair-correlation model. It
does not use OANDA practice NAV, place orders, reserve margin, or include gap,
financing, commission, tax, or unobserved slippage in the displayed cash risk.
If no point-in-time CAD conversion path exists, sizing is withheld rather than
invented.

## Batch reliability

Every scheduled model batch attempts all active pairs even when one provider
request or semantic validation fails. Successful pair records remain immutable
and idempotent; queue retries therefore revisit only work that has not already
completed against the same evidence and reference candle. A batch is marked
failed until every pair completes, and Operations shows the latest batch state,
attempt count, and per-pair error. The default structured-output allowance is
6,000 tokens while the existing per-request and aggregate spend caps remain in
force.

## Financing and commission sensitivity

Every activated paper result receives a separate immutable cost assessment
under `paper-cost-sensitivity-v1`. Gross pips remain unchanged. The assessment
reports three net-pip and net-R views:

- optimistic: observed bid/ask execution only;
- base stress: 3% adverse annual financing and 0.5 round-turn commission pips;
- conservative: 6% adverse annual financing, 1.0 round-turn commission pip,
  and the maximum rollover count allowed by hourly timing ambiguity.

Rollover windows use 5 p.m. `America/New_York` boundaries and the standard
Wednesday three-day charge. The model stores both minimum and maximum possible
financing days because intrabar entry and exit times are unknown. OANDA's
published formula is applied in pips using entry price, but the rates and
commission amounts above are stress assumptions—not observed account charges.
Exact rates can vary daily by pair, side, holiday, and account terms. Exact cash
cost and tax treatment remain blocked. Position sizing now has a point-in-time
CAD conversion, but financing and commission must not be applied to it until a
prospective cost-policy version consumes account-term snapshots.

Forward account-specific OANDA financing capture now runs hourly. These
immutable snapshots do not rewrite existing cost assessments; a later cost
policy version may consume only snapshots captured before each outcome. OANDA
currently omits commission terms for the configured practice account, so v1
commission sensitivities remain necessary.

## Spend limits

Defaults use Claude Sonnet 5 list rates and enforce:

- USD $0.10 estimated maximum per request;
- USD $2 per UTC day;
- USD $40 per UTC month.

The limits and model are environment configuration. A serialized reservation is
created before every provider call; reserved and uncertain attempts count
conservatively, and estimated versus actual cost remains distinct. Actual token
cost is stored on every successful record. The four-hour schedule remains disabled until both
`ANTHROPIC_API_KEY` is configured and `RECOMMENDATION_SCHEDULE_ENABLED=true` is
set after a successful manual generation.

## Operations

```bash
python manage.py generate_recommendations
python manage.py generate_recommendations USD_CAD
```

Portfolio admission remains a later prospective state machine. It must remain
separate from thesis scoring and must not reconstruct historical
recommendations.
