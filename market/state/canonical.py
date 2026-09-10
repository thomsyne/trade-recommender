"""Deterministic canonical serialization and hashing for market state.

Everything the engine persists — definition bodies, input manifests and output
payloads — is hashed through :func:`identity_digest`, which is a pure function
of the value's canonical JSON. To keep hashes reproducible across processes,
Python versions and PostgreSQL, the canonical form forbids the artifacts that
make floating point and locale-dependent numbers non-deterministic:

* ``float`` (and therefore ``NaN``/``inf``) is rejected — numerics must be
  exact integers or pre-formatted Decimal strings (:func:`format_decimal`);
* ``Decimal`` is rejected in a payload — callers format it to a string first,
  so the stored bytes are unambiguous;
* dict keys must be strings; ordering is normalized with ``sort_keys=True``.

This mirrors the repository convention (``forecasts/targets.identity_digest``)
while adding the explicit float/Decimal guard the Phase 4 brief requires.
"""

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal

#: Price/– quantum shared with market.technicals and forecasts (six decimals).
QUANTUM = Decimal("0.000001")


class NonCanonicalValue(ValueError):
    """A value cannot be serialized deterministically (float, Decimal, bad key)."""


def format_decimal(value, quantum=QUANTUM):
    """Format a Decimal-compatible value to a stable fixed-point string.

    Uses ROUND_HALF_EVEN so Python and PostgreSQL agree, and ``format(..., "f")``
    so there is never scientific notation or a locale separator.
    """
    return format(Decimal(value).quantize(quantum, rounding=ROUND_HALF_EVEN), "f")


def _reject_non_canonical(value):
    if isinstance(value, bool):
        return
    if isinstance(value, float):
        raise NonCanonicalValue("float is not canonical; use an int or a formatted Decimal string")
    if isinstance(value, Decimal):
        raise NonCanonicalValue("Decimal must be formatted to a string before serialization")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NonCanonicalValue("object keys must be strings")
            _reject_non_canonical(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_canonical(item)
        return
    if value is None or isinstance(value, (str, int)):
        return
    raise NonCanonicalValue(f"unsupported type in canonical payload: {type(value).__name__}")


def canonical_json(value):
    """Return the canonical JSON string of ``value`` or raise NonCanonicalValue."""
    _reject_non_canonical(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def identity_digest(value):
    """Return the SHA-256 hex digest of ``value``'s canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
