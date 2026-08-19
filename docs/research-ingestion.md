# Research ingestion contract

This slice records official macro evidence prospectively. It is a read-only
input ledger: no code in `research` issues, edits, resolves, or scores a
forecast.

## Current providers

| Jurisdiction | Release feed | Policy-rate series | Availability semantics |
|---|---|---|---|
| Canada | Bank of Canada press releases | Valet `V39079` | observation date + first retrieval |
| United States | Federal Reserve monetary releases | FRED `DFEDTARU` | observation date + first retrieval |
| Euro area | ECB press releases | ECB `FM.D.U2.EUR.4F.KR.DFR.LEV` | observation date + first retrieval |
| United Kingdom | Bank of England news | IADB `IUDBEDR` | observation date + first retrieval |

The policy-rate endpoints do not give a trustworthy release timestamp for these
daily policy-rate observations. `available_at` therefore uses the first time
this system retrieved a value. This is conservative and prevents historical
values from being treated as though the system knew them earlier.

The registry also covers inflation, unemployment, GDP, and housing for all four
economies. Statistics Canada uses bounded WDS vector requests except for its
small housing-starts table (a bounded official ZIP); BLS uses a fixed POST
adapter; ONS uses current generator CSVs; Eurostat uses filtered JSON-stat; and
UK housing uses HM Land Registry linked data. FRED carries official BEA GDP and
Census/HUD housing-start series.

Exact provider release timestamps are retained when supplied. Otherwise
`available_at` remains the first successful retrieval. Provider status and
footnotes are retained, and changed values append a vintage so revisions are
learned prospectively rather than reconstructed with hindsight.

## Retrieval boundary

`research.fetch` is the only network boundary. It requires:

- HTTPS and an exact host allowlist per source;
- no credentials in URL authority fields; query credentials required by a
  fixed provider adapter are redacted before URLs or fingerprints are stored;
- public DNS destinations (no private, loopback, link-local, or reserved IPs);
- destination validation again after each of at most three redirects;
- bounded connect/read time and decoded response size;
- an explicit content-type allowlist and stable user agent.

It is not an arbitrary-URL fetch API. RSS/XML is parsed with `defusedxml`.
Templates render normalized text with Django auto-escaping; raw bodies are
never rendered.

## Evidence and lineage

- `RawRetrieval` preserves the bounded body, URL, headers, retrieval time,
  content type, byte count, and SHA-256.
- `ResearchDocument` is the canonical release index.
- `DocumentRepresentation` links a source item to its raw retrieval.
- `MacroObservation` preserves every distinct value as a vintage. A changed
  value appends a revision rather than overwriting history.
- `ResearchDiscrepancy` records syndication, conflicts, and revisions.

Raw retrievals, representations, macro observations, economic events, and discrepancies reject
update/delete in both Django and PostgreSQL. Invalid but successfully retrieved
payloads are retained as quarantined raw evidence and do not normalize.

## Rights and model use

Only bounded official API/RSS payloads are currently retained, for private
research. Article full text is not collected, raw bodies are not exported, and
all sources remain `llm_processing_allowed=False`. Each source records its
rights URL and retention/deletion/export policy. A full provider-terms review
is still required before external-model processing or redistribution.

## Operations

Seeding creates four six-hour feed schedules, twenty daily macro schedules,
and a disabled hourly calendar schedule:

```bash
.venv/bin/python manage.py seed_research
.venv/bin/python manage.py ingest_research --series CA_POLICY_RATE
.venv/bin/python manage.py ingest_research \
  --feed bank-of-canada \
  --url https://www.bankofcanada.ca/content_type/press-releases/feed/
```

The EODHD economic-events adapter accepts `EODHD_API_KEY` (or the legacy alias
`EODHD_API_TOKEN`). A free API key does not include this endpoint: the
Fundamentals Data Feed entitlement is required and is advertised at USD $59.99
monthly or $599.90 annually. The hourly schedule remains disabled until a
manual bounded retrieval succeeds; a key alone cannot create a failing retry
loop. The dashboard likewise displays `CONNECTED` only after a recent accepted
retrieval. Confirm long-term retention and model-input rights with EODHD before
purchase. Trading Economics remains an unselected fallback pending a quote and
written rights.
