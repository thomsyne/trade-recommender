"""Fixed-path governance for the code-only v2 exploratory return calculator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research import exploratory_returns_v2 as calculator
from research import s2_policy_v2

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs/strategy/failed-break/v2"
ARTIFACT_PATH = DOCS / "exploratory-return-calculator-preregistration-v2.json"
REPORT_PATH = DOCS / "exploratory-return-calculator-architecture.md"

REPOSITORY_BASELINE = "139dff6a0dd07fda413476ec6d9b0bc5cfa24287"
SCHEMA = "failed-break-v2-exploratory-return-calculator-preregistration-v1"
IDENTITY = "failed-break-v2-exploratory-return-calculator-v1"
ARTIFACT_SHA256 = "92acc23cc194e530f525c92243466aa87adc1933b8e659b560ccf9dae3a3ec1a"
SELF_SHA256 = "7fd25e8b1a660c6b0b087c4b40eca43588b0018d659c281374f5213a31400d77"
REPORT_SHA256 = "ad5cb19100bb31910f08f47283281f09dbb92d725ff28b37034a1c409115ae3e"
CALCULATOR_SHA256 = "3a115b3d8f162f5a95262d03860bc1cde1581302193de320286563c0f533b514"
S2_ARTIFACT_SHA256 = "1d4b1f451a60d7c2ac37a2fe91849d463254b7751529324e52198003de1ae8dc"
S2_SELF_SHA256 = "e2d2a4880e0d900a150a6e801d940b32b09b8cd1435f283a87fe16555e059d72"
S1_ACCEPTANCE_SHA256 = "5760dd2dd60a2d6a6087b5116b085a8a3774db1512962af0622bc0e3eeed93d5"
GEOMETRY_SHA256 = "b3bc76fa4ac226793a24f11a9a65f9b549e7231ace11e399f6d81c1599e41fdc"
EVENT_SET_SHA256 = "8abb97a0e658d7079b9cfffd66259609b00f7c57aba89209a01cb5673df9fbd8"
BOUNDARY_PURGED_EVENT_KEY = "cbecf84cceff3e391963280179633853ea8f74b2dafe3ba93910f71aac002e77"


class GovernanceRefusal(ValueError):
    """Artifact, source, or authority failed closed."""


def require(condition, message):
    if not condition:
        raise GovernanceRefusal(message)


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def governed_event_keys() -> tuple[str, ...]:
    geometry = s2_policy_v2.geometry_v2.verify_committed()
    keys = tuple(sorted(row["physical_key"] for row in geometry["events"]))
    require(len(keys) == 82 and len(set(keys)) == 82, "governed event set changed")
    require(BOUNDARY_PURGED_EVENT_KEY not in keys, "boundary-purged event was admitted")
    return keys


def load_preregistration() -> dict:
    """Load the one committed artifact; caller paths and overrides do not exist."""
    try:
        raw = ARTIFACT_PATH.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == ARTIFACT_SHA256, "artifact file digest mismatch")
        artifact = json.loads(raw)
        require(canonical_bytes(artifact) + b"\n" == raw, "artifact bytes are not canonical")
        body = dict(artifact)
        require(
            body.pop("implementation_sha256", None) == SELF_SHA256 == digest(body),
            "self-hash mismatch",
        )
        policy = s2_policy_v2.load_policy()
        require(
            policy["policy_sha256"] == S2_SELF_SHA256
            and _source_hash(s2_policy_v2.ARTIFACT_PATH) == S2_ARTIFACT_SHA256,
            "effective S2 policy drift",
        )
        require(
            artifact["schema"] == SCHEMA
            and artifact["identity"] == IDENTITY
            and artifact["repository_baseline"] == REPOSITORY_BASELINE,
            "calculator identity changed",
        )
        require(
            artifact["authority"]
            == {
                "code_only_return_calculator_implementation": True,
                "database_access": False,
                "live_trading": False,
                "persistent_return_execution": False,
                "post_entry_real_outcome_access": False,
                "production_or_provider_access": False,
                "promotion": False,
                "real_return_calculation": False,
                "synthetic_verification": True,
            },
            "authority boundary changed",
        )
        require(
            artifact["override_prohibition"]
            == [
                "CLI",
                "DATA_ONLY",
                "DATABASE",
                "ENVIRONMENT",
                "OWNER",
                "SUCCESSFUL_OUTCOME",
                "THRESHOLD_REINTERPRETATION",
            ],
            "override prohibition changed",
        )
        sources = artifact["source_bindings"]
        require(
            sources["effective_v2_s2_policy"]["artifact_sha256"] == S2_ARTIFACT_SHA256
            and sources["effective_v2_s2_policy"]["self_sha256"] == S2_SELF_SHA256
            and sources["v2_s1_acceptance_sha256"] == S1_ACCEPTANCE_SHA256
            and sources["v2_geometry_sha256"] == GEOMETRY_SHA256
            and sources["v2_geometry_event_set_sha256"] == EVENT_SET_SHA256,
            "upstream identity substitution",
        )
        require(
            sources["detector_sha256"]
            == "3b9188749c10581d7518e25838a2cb65704d1329e7ebe3061cd7fe4b82115861"
            and sources["dataset_identity"] == "oanda-ba-ny17-friday-provider-observed-v2"
            and sources["dataset_version"] == "phase-2b1r-v2",
            "detector or dataset identity substitution",
        )
        require(
            sources["source_files"]["research/exploratory_returns_v2.py"]
            == CALCULATOR_SHA256
            == _source_hash(ROOT / "research/exploratory_returns_v2.py"),
            "calculator source drift",
        )
        require(_source_hash(REPORT_PATH) == REPORT_SHA256, "architecture report drift")
        semantics = artifact["calculation_semantics"]
        require(semantics["physical_event_count"] == 82, "event count changed")
        require(
            semantics["terminal_classifications"] == list(calculator.TERMINALS), "terminal drift"
        )
        require(
            semantics["cost_grid"]
            == {
                "additional_slippage_pips": "0",
                "annual_financing_rates": ["-0.06", "-0.03", "0", "0.03", "0.06"],
                "axes": ["commission_pips", "annual_financing_rate"],
                "cell_count": 15,
                "commission_pips": ["0", "0.5", "1"],
            },
            "cost grid changed",
        )
        require(semantics["risk_cad"] == ["25", "50", "100"], "fixed-risk grid changed")
        require(semantics["development_months"] == 108, "calendar coverage changed")
        require(semantics["bootstrap_replicates"] == 10_000, "bootstrap changed")
        require(semantics["geometry_sigma_R"] == ["0.5", "1", "1.5"], "geometry sigma changed")
        require(semantics["sensitivity_sigma_R"] == ["0.5", "1", "2"], "sensitivity sigma changed")
        require(semantics["grids_interchangeable"] is False, "sigma grids became interchangeable")
        return artifact
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise GovernanceRefusal("incomplete calculator preregistration") from error


def readiness() -> dict:
    artifact = load_preregistration()
    return {
        "artifact_sha256": ARTIFACT_SHA256,
        "code_only_implementation": "READY",
        "governed_physical_events": artifact["calculation_semantics"]["physical_event_count"],
        "persistent_return_execution_authorized": False,
        "post_entry_real_outcome_access_authorized": False,
        "promotion_permanently_prohibited": True,
        "self_sha256": SELF_SHA256,
        "synthetic_verification_only": True,
    }


def calculate_governed_real_cohort(*_args, **_kwargs):
    load_preregistration()
    raise GovernanceRefusal("persistent real-outcome return execution is separately unauthorized")


def require_promotion(*_args, **_kwargs):
    load_preregistration()
    raise GovernanceRefusal("promotion and live trading are permanently prohibited")
