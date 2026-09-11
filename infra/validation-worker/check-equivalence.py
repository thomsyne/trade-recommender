"""Manual 32-day development equivalence check after the Linux registration freeze."""

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from market.state.canonical import canonical_json, identity_digest
from research.validation_batch import run
from research.validation_data import audit_cache
from research.validation_registration import Catalog
from research.validation_reports import publish_immutable
from research.validation_worker import verify_projection


def normalized(body):
    body = json.loads(canonical_json(body))
    # Only the new registration and its derived IDs differ. Keep every decision,
    # opportunity, cost, outcome, exposure state and original Phase5 identity.
    body.pop("registration")
    body["key"].pop("registration")
    body.pop("predecessor")  # Each actual chain is independently replay-verified.
    for row in body["rows"]:
        row.pop("evaluation_identity")
        for result in row["scenarios"].values():
            if result["state"] == "modeled":
                result.pop("registration_sha256")
                result.pop("identity")
    return body


def main():
    root = Path(".candidate-data/phase55-v1")
    reference_path = Path(sys.argv[1])
    frozen = json.loads(Path("docs/phase5.5/frozen-registration-v5.json").read_text())
    reference = json.loads(reference_path.read_text())
    binding = json.loads(Path("docs/phase5.5/worker-transfer.json").read_text())
    verify_projection(root / "acquisition.sqlite3", binding)
    strategies = ("phase5-sweep-reversal-v1", "phase5-acceptance-continuation-v1")
    start = datetime.fromisoformat("2019-01-07T00:00:00+00:00")
    end = start + timedelta(days=32)
    expected_keys = {
        (s, (start + timedelta(days=d)).isoformat()) for s in strategies for d in range(32)
    }
    expected = {(b["key"]["strategy"], b["key"]["start"]): b for b in reference}
    assert len(reference) == len(expected) == 64 and set(expected) == expected_keys
    assert all(b["key"]["instrument"] == "EUR_USD" for b in reference)
    catalog = Catalog(root / "linux-equivalence.sqlite3")
    try:
        identity, body = catalog.register(audit_cache(root / "acquisition.sqlite3"))
        assert {"identity": identity, "body": body} == frozen
        for strategy in strategies:
            run(
                catalog,
                identity,
                root / "acquisition.sqlite3",
                strategy,
                "EUR_USD",
                start,
                start + timedelta(days=16),
            )
            run(
                catalog,
                identity,
                root / "acquisition.sqlite3",
                strategy,
                "EUR_USD",
                start + timedelta(days=16),
                end,
            )
        catalog.close()
        # Cold restart has no volatile semantic proofs. It must reconstruct them.
        catalog = Catalog(root / "linux-equivalence.sqlite3")
        for strategy in strategies:
            run(
                catalog,
                identity,
                root / "acquisition.sqlite3",
                strategy,
                "EUR_USD",
                start + timedelta(days=16),
                end,
            )
            catalog.verify_chain(identity, strategy, "EUR_USD", stop=end, collect=False)
        actual = [json.loads(r[0]) for r in catalog.db.execute("SELECT body FROM checkpoint")]
        assert len(actual) == 64
        for checkpoint in actual:
            key = checkpoint["key"]
            assert normalized(checkpoint) == normalized(expected[key["strategy"], key["start"]]), (
                key["strategy"],
                key["start"],
            )
        evidence = {
            "registration": identity,
            "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
            "checkpoints": len(actual),
            "all_decisions_costs_outcomes_and_end_states_equal": True,
            "cold_resume_idempotent": True,
            "scope": "32_days_two_strategies_EUR_USD_not_full_population",
            "holdout": "physically_absent_not_accessed",
            "activation": "forbidden",
        }
        evidence["identity"] = identity_digest(evidence)
        publish_immutable(root / "linux-equivalence.json", canonical_json(evidence))
        print(canonical_json(evidence))
    finally:
        catalog.close()


if __name__ == "__main__":
    main()
