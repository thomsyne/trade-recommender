"""Registration and fail-closed loading of immutable market-state definitions.

A definition body is a canonical JSON object binding the algorithm identifiers,
feature names, price basis, rounding, calendar/session policy, lookbacks,
thresholds and missing-data policy of a market-state version. Bodies are
content-addressed: registering the same body twice returns the same row, and an
unknown or tampered ``(key, version)`` fails closed rather than silently
computing against an undefined contract.
"""

from market.models import MarketStateDefinition
from market.state.canonical import NonCanonicalValue, canonical_json, identity_digest

#: The keys every definition body must carry. Missing keys fail closed.
REQUIRED_DEFINITION_KEYS = frozenset(
    {
        "algorithms",
        "features",
        "price_basis",
        "rounding",
        "calendar_policy",
        "missing_data_policy",
        "lookbacks",
        "thresholds",
    }
)


class DefinitionError(ValueError):
    """A definition body is malformed, unknown, or fails its hash check."""


def validate_definition_body(body):
    if not isinstance(body, dict):
        raise DefinitionError("definition body must be a JSON object")
    missing = REQUIRED_DEFINITION_KEYS - set(body)
    if missing:
        raise DefinitionError(f"definition body missing required keys: {sorted(missing)}")
    try:
        canonical_json(body)  # rejects float/Decimal/non-string keys
    except NonCanonicalValue as exc:
        raise DefinitionError(str(exc)) from exc


def register_definition(key, version, body):
    """Register (or return the existing) definition for ``body``.

    Content-addressed and idempotent: the same body always resolves to the same
    row. Registering the same content under a different ``(key, version)`` — or a
    different body under an existing ``(key, version)`` — fails closed.
    """
    validate_definition_body(body)
    digest = identity_digest(body)
    existing = MarketStateDefinition.objects.filter(definition_sha256=digest).first()
    if existing is not None:
        if (existing.key, existing.version) != (key, version):
            raise DefinitionError(
                f"definition content already registered as {existing.key}@{existing.version}"
            )
        return existing
    clash = MarketStateDefinition.objects.filter(key=key, version=version).first()
    if clash is not None:
        raise DefinitionError(f"{key}@{version} already registered with different content")
    return MarketStateDefinition.objects.create(key=key, version=version, definition=body)


def load_definition(key, version):
    """Return a registered definition, failing closed on unknown or tampered rows."""
    try:
        definition = MarketStateDefinition.objects.get(key=key, version=version)
    except MarketStateDefinition.DoesNotExist as exc:
        raise DefinitionError(f"unknown market-state definition {key}@{version}") from exc
    if identity_digest(definition.definition) != definition.definition_sha256:
        raise DefinitionError(f"definition hash mismatch for {key}@{version}; refusing to use")
    return definition
