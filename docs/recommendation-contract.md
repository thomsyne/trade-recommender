# Governed recommendation contract v2

This contract permits one bounded model assessment of an immutable
`PairEvidenceSnapshot`. It does not authorize broker access, order placement,
portfolio sizing, silent source reweighting, or historical sentiment replay.

## Input boundary

The provider receives only the selected snapshot, its information cutoff, a
frozen daily reference midpoint and neutral band, the fixed five-session
horizon, and stable evidence IDs added to each included record. It cannot browse
or call tools. News text is explicitly untrusted data.
The packet contains bounded normalized market/research fields and filters out
any news item not explicitly marked eligible for model processing.

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
- conditional entry, target, invalidation, and five-session expiry;
- directional level ordering;
- at least one technical and one non-technical citation for a setup.

Malformed or semantically invalid output creates no recommendation. There is no
repair prompt in v1: failure is visible and retryable without letting the model
negotiate the contract.

## Immutable audit record

`Recommendation` stores the exact transformed input packet, input SHA-256,
source snapshot, provider/model/contract version, provider response ID, token
counts, calculated API cost, validated output, information cutoff, frozen daily
reference candle/midpoint/neutral band, and optional mechanical tactical control.
Django and PostgreSQL both reject updates and deletes. Re-running one
provider/model against the same evidence and reference is idempotent.

The model recommendation and mechanical forecast remain separate records. A
recommendation cannot mutate evidence, replace the control, or count as an
executed trade.

## Prospective resolution and calibration

Version 2 defines up, neutral, and down against the midpoint close of the fifth
subsequently completed OANDA daily candle. The neutral band is frozen at issue
time as the greater of 0.25 × daily ATR(14) and 2 × closing spread. Equality is
neutral. `RecommendationResolution` immutably stores the endpoint, outcome,
multiclass Brier score, and directional hit or miss. Abstentions receive a Brier
score but no directional hit label.

Version 1 recommendations are deliberately excluded: their confidence number
did not identify a precise event, so retroactive interpretation would create
false calibration. The dashboard remains explicitly insufficient-sample until
30 version 2 outcomes resolve. It is descriptive only and cannot alter prompts,
sources, weights, or execution.

## Paper setup lifecycle

Directional version 2 setups are monitored only against completed hourly OANDA
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

These are paper observations, not orders. Gross pips embed bid/ask execution but
exclude financing, commission, sizing, leverage, and taxes. They are reported
separately from probabilistic thesis calibration and remain insufficient-sample
until 30 activated setups resolve.

## Currency exposure guardrails

Every unresolved directional version 2 setup is decomposed deterministically:
buying BASE/QUOTE is long base and short quote; selling it is short base and
long quote. Waiting entries remain included because they can still activate,
while abstentions, legacy recommendations, and completed paper setups are
excluded. Entered and waiting states remain visibly distinct.

The Exposure page reports gross and net setup equivalents, repeated
same-direction currency factors, and opposing factors. More than two unresolved
setup equivalents in one currency direction breaches the declared advisory
cap. This is direct factor accounting, not an estimated pair-correlation model.
Until sizing exists, one setup equivalent is not a risk or cash amount and the
guardrail cannot place, resize, or block an order.

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
Exact rates can vary daily by pair, side, holiday, and account terms. Cash cost,
CAD conversion, and tax treatment remain blocked until position sizing and
point-in-time account-specific data exist.

## Spend limits

Defaults use Claude Sonnet 5 list rates and enforce:

- USD $0.10 estimated maximum per request;
- USD $2 per UTC day;
- USD $40 per UTC month.

The limits and model are environment configuration. Actual token cost is stored
on every successful record. The four-hour schedule remains disabled until both
`ANTHROPIC_API_KEY` is configured and `RECOMMENDATION_SCHEDULE_ENABLED=true` is
set after a successful manual generation.

## Operations

```bash
python manage.py generate_recommendations
python manage.py generate_recommendations USD_CAD
```

The next contract may add portfolio sizing and point-in-time account-specific
cost capture. It must remain separate from thesis scoring and must not
reconstruct historical recommendations.
