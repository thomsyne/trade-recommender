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

## Official release calendar

Upcoming releases are collected daily without a paid calendar subscription:

| Jurisdiction | Official schedule | Current tracked coverage | Time semantics |
|---|---|---|---|
| Canada | Statistics Canada key-indicator JSON | CPI, Labour Force Survey, GDP, building permits | 08:30 America/Toronto, as documented for *The Daily* |
| United States | BEA machine-readable release dates | GDP and personal income/PCE | Exact UTC timestamp supplied by BEA |
| United Kingdom | ONS upcoming-release RSS | CPI, labour market, GDP, house prices | Exact UTC timestamp supplied by ONS |
| Euro area | Eurostat euro-indicator iCalendar | HICP, unemployment, GDP, house prices | Date only; no time is inferred |

This is deliberately honest partial coverage. BLS blocks automated calendar
retrieval from this environment, and Census housing plus Fed, Bank of Canada,
Bank of England, and ECB decisions are not silently replaced by unofficial
sources. The dashboard names those gaps. EODHD remains disabled because its
free key excludes economic events; it is not needed for the official schedule.

Each normalized event links to its related macro series where an exact mapping
exists. Consensus is always null because official schedules do not provide it.
Actual values continue through `MacroObservation`; they are never inferred from
a schedule. Raw schedule snapshots are immutable, and a changed date or event
payload appends a new event vintage instead of rewriting the earlier capture.

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
four daily official-calendar schedules, and a disabled optional EODHD schedule:

```bash
.venv/bin/python manage.py seed_research
.venv/bin/python manage.py ingest_research --series CA_POLICY_RATE
.venv/bin/python manage.py ingest_research \
  --feed bank-of-canada \
  --url https://www.bankofcanada.ca/content_type/press-releases/feed/
.venv/bin/python manage.py ingest_research \
  --calendar eurostat \
  --parser eurostat \
  --url 'https://ec.europa.eu/eurostat/o/calendars/eventsIcal?theme=2&category=2'
```

The EODHD adapter still accepts `EODHD_API_KEY` (or the legacy alias
`EODHD_API_TOKEN`) but its schedule remains disabled. Trading Economics also
remains an unselected consensus fallback pending a quote and written rights.
