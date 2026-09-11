"""Phase 7 pure, versioned semantics. No provider, scheduler or outcome dependency.

Frozen inputs are the only replay source. SQL admits identity/shape; this module
recomputes semantics, including hash-consistent but incorrectly ranked packets.
"""

import hashlib
import json
import re
from datetime import UTC, datetime

VERSION = "evidence-quality-v1"
FIELDS = (
    "raw_body",
    "headline",
    "supplied_summary",
    "normalized_fact",
    "derived_label",
    "url_attribution",
)
USES = (
    "private_storage",
    "private_display",
    "deterministic_processing",
    "external_llm",
    "internal_report",
    "notification",
    "redistribution",
)
STATES = {"allowed", "prohibited", "unknown", "review-required", "expired", "superseded"}
CLASSES = {
    "exact_duplicate",
    "immaterial_repeat",
    "title_edit",
    "publication_time_edit",
    "summary_edit",
    "provider_correction",
    "material_disagreement",
    "retraction",
    "unclassified_change",
}
MATERIAL = {"provider_correction", "material_disagreement", "retraction"}
CURRENCIES = {
    "EUR": ("euro", "eurozone", "european", "ecb", "european central bank"),
    "USD": ("dollar", "united states", "federal reserve", "fed", "us"),
    "CAD": ("canada", "canadian", "bank of canada", "boc"),
    "GBP": ("britain", "british", "united kingdom", "bank of england", "boe"),
    "JPY": ("japan", "japanese", "bank of japan", "boj"),
    "CHF": ("swiss", "switzerland", "snb"),
    "AUD": ("australia", "australian", "rba"),
    "NZD": ("new zealand", "rbnz"),
}
MACRO = (
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
CRYPTO = (
    "bitcoin",
    "crypto",
    "cryptocurrency",
    "ethereum",
    "ether",
    "blockchain",
    "token",
    "stablecoin",
)
BANKS = (
    "ecb",
    "federal reserve",
    "bank of canada",
    "boc",
    "bank of england",
    "boe",
    "bank of japan",
    "snb",
    "rba",
    "rbnz",
)
RELEASES = ("inflation", "employment", "gdp", "interest rate")
SYSTEMIC = ("global financial crisis", "global liquidity", "systemic banking crisis")


class EvidenceError(ValueError):
    """Only fixed safe codes cross the caller boundary."""


def require(condition, code="invalid_evidence"):
    if not condition:
        raise EvidenceError(code)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def closed(value, keys):
    require(type(value) is dict and set(value) == set(keys), "invalid_shape")


def instant(value):
    try:
        result = datetime.fromisoformat(value)
        require(result.tzinfo is not None, "invalid_time")
        require(result.utcoffset().total_seconds() == 0, "noncanonical_time")
        return result
    except (TypeError, ValueError, AttributeError):
        raise EvidenceError("invalid_time") from None


def iso(value):
    require(value.tzinfo is not None, "invalid_time")
    return value.astimezone(UTC).isoformat()


def words(text, values):
    return any(re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", text, re.I) for v in values)


def validate_review(review):
    closed(
        review,
        (
            "version",
            "source_id",
            "processor",
            "terms_url",
            "terms_sha256",
            "reviewer",
            "reviewed_at",
            "expires_at",
            "jurisdiction",
            "attribution",
            "retention",
            "deletion",
            "rationale",
            "decisions",
            "supersedes",
        ),
    )
    require(review["version"] == VERSION, "unknown_version")
    require(type(review["source_id"]) is int and review["source_id"] > 0)
    for key in (
        "processor",
        "terms_url",
        "reviewer",
        "jurisdiction",
        "attribution",
        "retention",
        "deletion",
        "rationale",
    ):
        require(type(review[key]) is str and 0 < len(review[key]) <= 2000)
    require(review["terms_url"].startswith("https://"))
    require(re.fullmatch("[a-f0-9]{64}", review["terms_sha256"]) is not None)
    require(
        review["supersedes"] is None
        or re.fullmatch("[a-f0-9]{64}", review["supersedes"]) is not None
    )
    require(instant(review["expires_at"]) > instant(review["reviewed_at"]))
    closed(review["decisions"], FIELDS)
    for field in FIELDS:
        closed(review["decisions"][field], USES)
        require(all(state in STATES for state in review["decisions"][field].values()))


def permission(review, *, source_id, field, use, processor, cutoff):
    if review is None:
        return "unknown"
    validate_review(review)
    if review["source_id"] != source_id or review["processor"] != processor:
        return "unknown"
    if instant(review["reviewed_at"]) > cutoff:
        return "unknown"
    if instant(review["expires_at"]) <= cutoff:
        return "expired"
    return review["decisions"][field][use]


def validate_representation(rep):
    closed(
        rep,
        (
            "version",
            "kind",
            "document_id",
            "observation_id",
            "retrieval_id",
            "retrieval_sha256",
            "source_id",
            "source_item_id",
            "canonical_hash",
            "canonical_url",
            "headline",
            "supplied_summary",
            "normalized_fact",
            "published_at",
            "first_observed_at",
            "retrieved_at",
            "language",
            "content_type",
            "storage_review_sha256",
            "quality",
        ),
    )
    require(rep["version"] == VERSION, "unknown_version")
    require(rep["kind"] in {"news", "macro"})
    require((rep["document_id"] is not None) == (rep["kind"] == "news"))
    require((rep["observation_id"] is not None) == (rep["kind"] == "macro"))
    for key in ("retrieval_id", "source_id"):
        require(type(rep[key]) is int and rep[key] > 0)
    for key in ("retrieval_sha256", "canonical_hash", "storage_review_sha256"):
        require(type(rep[key]) is str and re.fullmatch("[a-f0-9]{64}", rep[key]) is not None)
    for key in (
        "source_item_id",
        "canonical_url",
        "headline",
        "supplied_summary",
        "normalized_fact",
        "language",
        "content_type",
    ):
        require(type(rep[key]) is str and len(rep[key]) <= 12000)
    require(rep["source_item_id"] and rep["language"] and rep["content_type"])
    if rep["published_at"] is not None:
        instant(rep["published_at"])
    require(instant(rep["first_observed_at"]) <= instant(rep["retrieved_at"]))
    closed(
        rep["quality"],
        (
            "retrieval_integrity",
            "timestamp_precision",
            "source_tier",
            "directness",
            "corroboration",
        ),
    )
    for key, allowed in {
        "retrieval_integrity": {"hash_checked", "unknown", "rejected"},
        "timestamp_precision": {"provider_exact", "date_only", "retrieval_only", "unknown"},
        "source_tier": {"primary", "secondary", "unknown"},
        "directness": {"direct", "reported", "unknown"},
        "corroboration": {"independent", "single_source", "unknown"},
    }.items():
        require(rep["quality"][key] in allowed)


def classify_change(earlier, later, declaration=None):
    validate_representation(earlier)
    validate_representation(later)
    require(earlier["canonical_hash"] == later["canonical_hash"], "cross_document")
    fields = [
        key
        for key in ("headline", "published_at", "supplied_summary", "normalized_fact")
        if earlier[key] != later[key]
    ]
    if declaration is not None:
        require(declaration in MATERIAL, "invalid_declaration")
        category = declaration
    elif not fields:
        category = "exact_duplicate" if digest(earlier) == digest(later) else "immaterial_repeat"
    elif fields == ["headline"]:
        category = "title_edit"
    elif fields == ["published_at"]:
        category = "publication_time_edit"
    elif fields == ["supplied_summary"]:
        category = "summary_edit"
    else:
        category = "unclassified_change"
    return {"class": category, "changed_fields": fields}


def conflict_state(events, cutoff):
    known = [e for e in events if instant(e["known_at"]) <= cutoff]
    for e in events:
        closed(e, ("digest", "known_at", "class", "changed_fields"))
        require(e["class"] in CLASSES)
    if any(e["class"] in MATERIAL for e in known):
        return "material"
    if any(e["class"] not in {"exact_duplicate", "immaterial_repeat"} for e in known):
        return "unknown"
    if known:
        return "nonmaterial"
    return "post-cutoff" if events else "none"


def relevance(rep, instrument, cutoff, conflict):
    parts = instrument.split("_")
    require(len(parts) == 2 and all(p in CURRENCIES for p in parts), "unsupported_instrument")
    text = rep["headline"]
    reasons = []
    score = 0
    for role, currency in zip(("base", "quote"), parts, strict=True):
        if words(text, (currency,) + CURRENCIES[currency]):
            reasons.append(f"{role}_currency_country_region:{currency}")
            score += 40
    linked = bool(reasons)
    macro = words(text, MACRO)
    crypto = words(text, CRYPTO) or "coindesk" in rep["canonical_url"].lower()
    systemic = words(text, SYSTEMIC)
    if crypto and not (linked and macro):
        return {"score": 0, "reasons": ["crypto_without_explicit_fx_macro_link"]}
    if not linked and not systemic:
        return {"score": 0, "reasons": ["no_pair_or_systemic_link"]}
    if linked and words(text, BANKS):
        score += 20
        reasons.append("central_bank")
    if linked and words(text, RELEASES):
        score += 10
        reasons.append("declared_release")
    if crypto:
        reasons.append("explicit_cross_market_link")
    if systemic:
        score += 30
        reasons.append("systemic_global")
    if rep["quality"]["directness"] == "direct":
        score += 5
        reasons.append("direct_source")
    published = instant(rep["published_at"]) if rep["published_at"] else None
    if published and 0 <= (cutoff - published).total_seconds() < 86400:
        score += 5
        reasons.append("within_one_day")
    if conflict in {"material", "unknown"}:
        score -= 15
        reasons.append("unresolved_conflict_penalty")
    return {"score": max(score, 1), "reasons": reasons}


def build_packet(*, instrument, cutoff, candidates, required_ids):
    """Candidates are a complete, frozen caller-declared universe, never top-N input.

    Inclusion requires independently cleared deterministic and external use. Raw
    body and URL are never external fields even when terms permit them.
    """
    instant(cutoff)
    require(type(candidates) is list and type(required_ids) is list)
    require(required_ids == sorted(set(required_ids)), "duplicate_required")
    now = instant(cutoff)
    entries = []
    ids = []
    for candidate in candidates:
        closed(
            candidate,
            ("id", "representation", "known_at", "rights", "rights_known_at", "conflicts", "role"),
        )
        rep = candidate["representation"]
        validate_representation(rep)
        require(candidate["id"] == digest(rep), "representation_digest")
        require(candidate["role"] in {"required", "contextual", "optional"})
        require(
            (candidate["role"] == "required") == (candidate["id"] in required_ids), "required_role"
        )
        ids.append(candidate["id"])
        conflict = conflict_state(candidate["conflicts"], now)
        rank = relevance(rep, instrument, now, conflict)
        reasons = []
        published = instant(rep["published_at"]) if rep["published_at"] else None
        if (
            instant(candidate["known_at"]) > now
            or instant(rep["retrieved_at"]) > now
            or (published and published > now)
        ):
            reasons.append("future")
        if not published:
            reasons.append("missing_publication_time")
        elif (now - published).total_seconds() > 259200:
            reasons.append("stale")
        if rep["quality"]["retrieval_integrity"] != "hash_checked":
            reasons.append("retrieval_unavailable")
        if rank["score"] == 0:
            reasons.append("irrelevant")
        rights = candidate["rights"]
        rights_available = rights is not None and instant(candidate["rights_known_at"]) <= now
        decisions = {}
        for field in ("headline", "supplied_summary", "normalized_fact", "derived_label"):
            decisions[field] = {
                use: permission(
                    rights if rights_available else None,
                    source_id=rep["source_id"],
                    field=field,
                    use=use,
                    processor="anthropic",
                    cutoff=now,
                )
                for use in ("deterministic_processing", "external_llm")
            }
        if any(state != "allowed" for state in decisions["headline"].values()):
            reasons.append("rights_blocked")
        if candidate["role"] == "required" and (
            conflict in {"material", "unknown"}
            or rep["quality"]["timestamp_precision"] != "provider_exact"
        ):
            reasons.append("required_unresolved")
        permitted = [
            f for f, uses in decisions.items() if all(v == "allowed" for v in uses.values())
        ]
        entries.append(
            {
                "candidate": candidate,
                "conflict_at_cutoff": conflict,
                "relevance": rank,
                "rights_by_field": decisions,
                "permitted_fields": permitted,
                "exclusions": reasons,
                "rank": None,
            }
        )
    require(len(set(ids)) == len(ids), "duplicate_evidence")
    entries.sort(
        key=lambda e: (
            -e["relevance"]["score"],
            e["candidate"]["representation"]["canonical_hash"],
            e["candidate"]["id"],
        )
    )
    seen = set()
    admitted = 0
    for index, entry in enumerate(entries, 1):
        entry["rank"] = index
        identity = entry["candidate"]["representation"]["canonical_hash"]
        if not entry["exclusions"]:
            if identity in seen:
                entry["exclusions"].append("duplicate_document")
            else:
                seen.add(identity)
                if admitted == 20:
                    entry["exclusions"].append("cap")
                else:
                    admitted += 1
    available = {e["candidate"]["id"] for e in entries if not e["exclusions"]}
    missing = sorted(set(required_ids) - available)
    counts = {}
    for e in entries:
        for reason in e["exclusions"]:
            counts[reason] = counts.get(reason, 0) + 1
    body = {
        "schema": VERSION,
        "policies": {key: VERSION for key in ("rights", "relevance", "conflict", "packet")},
        "instrument": instrument,
        "cutoff": cutoff,
        "required_ids": required_ids,
        "entries": entries,
        "candidate_count": len(entries),
        "included_count": admitted,
        "excluded_counts": counts,
        "unavailable_required": missing,
        "readiness": "abstain" if missing else "ready",
    }
    return body


def replay(packet):
    closed(
        packet,
        (
            "schema",
            "policies",
            "instrument",
            "cutoff",
            "required_ids",
            "entries",
            "candidate_count",
            "included_count",
            "excluded_counts",
            "unavailable_required",
            "readiness",
        ),
    )
    require(packet["schema"] == VERSION, "unknown_version")
    expected = build_packet(
        instrument=packet["instrument"],
        cutoff=packet["cutoff"],
        candidates=[e["candidate"] for e in packet["entries"]],
        required_ids=packet["required_ids"],
    )
    require(canonical(expected) == canonical(packet), "semantic_replay_mismatch")
    return canonical(expected).encode()
