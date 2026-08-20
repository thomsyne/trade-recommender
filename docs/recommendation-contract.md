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

The next contract may add setup activation, target/invalidation ordering with
lower-timeframe bid/ask evidence, and paper results. It must remain separate
from thesis scoring and must not reconstruct historical recommendations.
