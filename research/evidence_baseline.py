"""Read-only deployed Phase7 aggregate audit, runnable from in-memory source.

This standalone file deliberately imports no Phase7 model or unmerged code.
Run main(metadata_only=True) first. Never print input rows or raw exceptions.
"""

import hashlib
import json
import os
import re
from collections import Counter


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def main(*, metadata_only=False, code_sha256):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.db import connection

    if connection.in_atomic_block:
        raise RuntimeError("audit_connection_not_idle")
    connection.close()
    connection.ensure_connection()
    connection.set_autocommit(False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute("SET LOCAL lock_timeout = '2s'")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("audit_not_read_only")
            cursor.execute(
                "SELECT current_database(), current_setting('server_version'), transaction_timestamp(), txid_current_snapshot()::text"
            )
            db, version, cutoff, snapshot = cursor.fetchone()
            cursor.execute(
                "SELECT count(*), min(generated_at), max(generated_at), max(information_cutoff) FROM forecasts_recommendation WHERE generated_at <= %s",
                [cutoff],
            )
            count, first, last, last_cutoff = cursor.fetchone()
            cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
            migrations = cursor.fetchall()
            output = {
                "schema": "phase7-baseline-v1",
                "status": "new_baseline_not_historical_reproduction",
                "source": "deployed-primary",
                "database": db,
                "server_version": version,
                "transaction_cutoff": cutoff.isoformat(),
                "transaction_snapshot": snapshot,
                "code_sha256": code_sha256,
                "migrations_sha256": sha(migrations),
                "recommendations": count,
                "first_generated_at": str(first),
                "last_generated_at": str(last),
                "last_information_cutoff": str(last_cutoff),
                "historical_claims_verified": False,
            }
            if not metadata_only:
                cursor.execute(
                    "SELECT r.id, i.code, r.contract_version, r.generated_at, r.information_cutoff, r.input_payload->'evidence'->'recent_news' FROM forecasts_recommendation r JOIN market_instrument i ON i.id=r.instrument_id WHERE r.generated_at <= %s ORDER BY r.id",
                    [cutoff],
                )
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT id, canonical_hash FROM research_researchdocument ORDER BY id"
                )
                documents = dict(cursor.fetchall())
                cursor.execute(
                    "SELECT entity_key, observed_at FROM research_researchdiscrepancy WHERE kind='conflict' AND observed_at <= %s ORDER BY entity_key, observed_at, id",
                    [cutoff],
                )
                discrepancies = cursor.fetchall()
                cursor.execute(
                    "SELECT p.jurisdiction, count(*) FROM research_documentrepresentation r JOIN research_rawretrieval x ON x.id=r.retrieval_id JOIN research_sourcepolicy p ON p.id=x.source_policy_id WHERE x.fetched_at <= %s GROUP BY p.jurisdiction ORDER BY p.jurisdiction",
                    [cutoff],
                )
                output["current_policy_representation_jurisdiction"] = dict(cursor.fetchall())
                output["audit_input_sha256"] = sha(
                    [
                        rows,
                        documents,
                        discrepancies,
                        output["current_policy_representation_jurisdiction"],
                    ]
                )
                output.update(analyze(rows, documents, discrepancies))
            rendered = encode(output)
            if len(rendered) > 16000:
                raise RuntimeError("audit_output_bound")
            print(rendered)
    finally:
        connection.rollback()
        connection.close()


def analyze(rows, documents, discrepancies):
    first_conflict = {}
    for key, observed in discrepancies:
        first_conflict[key] = min(observed, first_conflict.get(key, observed))
    counts = Counter()
    pairs, contracts, jurisdiction = Counter(), Counter(), Counter()
    currencies = {
        "EUR": ("eur", "euro", "eurozone", "european", "ecb"),
        "USD": ("usd", "dollar", "united states", "federal reserve", "fed", "us"),
        "CAD": ("cad", "canada", "canadian", "bank of canada", "boc"),
        "GBP": ("gbp", "britain", "british", "united kingdom", "bank of england", "boe"),
    }
    crypto = (
        "bitcoin",
        "crypto",
        "cryptocurrency",
        "ethereum",
        "ether",
        "blockchain",
        "token",
        "stablecoin",
    )
    macro = (
        "inflation",
        "interest rate",
        "central bank",
        "liquidity",
        "monetary",
        "employment",
        "gdp",
        "recession",
        "treasury",
        "yield",
    )

    def matches(title, terms):
        return any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", title, re.I) for t in terms)

    for _, pair, contract, issued, cutoff, slots in rows:
        pairs[pair] += 1
        contracts[str(contract)] += 1
        if type(slots) is str:
            slots = json.loads(slots)
        if type(slots) is not list:
            counts["missing_or_malformed_news_envelope"] += 1
            continue
        known_in_rec = False
        seen = set()
        for slot in slots:
            counts["slots"] += 1
            if type(slot) is not dict:
                counts["malformed_slots"] += 1
                continue
            jurisdiction[str(slot.get("jurisdiction", "unknown"))] += 1
            title = slot.get("title")
            if type(title) is not str:
                counts["missing_title"] += 1
            else:
                terms = macro + tuple(
                    t
                    for currency in pair.split("_")
                    for t in currencies.get(currency, (currency.lower(),))
                )
                if matches(title, crypto) and not matches(title, terms):
                    counts["crypto_without_obvious_title_link"] += 1
            doc = slot.get("document_id")
            if type(doc) is not int or doc not in documents:
                counts["missing_or_unresolvable_document_id"] += 1
                continue
            if doc in seen:
                counts["repeated_document_slots"] += 1
                continue
            seen.add(doc)
            counts["distinct_recommendation_document_references"] += 1
            conflict = first_conflict.get("document:" + documents[doc])
            if conflict:
                if conflict <= issued:
                    counts["references_conflict_known_at_issuance"] += 1
                    known_in_rec = True
                else:
                    counts["references_conflict_learned_later"] += 1
                if conflict <= cutoff:
                    counts["references_conflict_known_at_information_cutoff"] += 1
        counts["recommendations_conflict_known_at_issuance"] += known_in_rec
    numerator = counts["crypto_without_obvious_title_link"]
    denominator = counts["slots"]
    return {
        "counts": dict(counts),
        "pairs": dict(pairs),
        "contracts": dict(contracts),
        "frozen_slot_jurisdiction": dict(jurisdiction),
        "crypto_diagnostic": {
            "version": "lexical-title-v1",
            "numerator": numerator,
            "denominator_all_slots": denominator,
            "percent": round(100 * numerator / denominator, 6) if denominator else None,
        },
        "historical_timestamp_semantics": "legacy observed_at, not materiality or proof of truth",
    }
