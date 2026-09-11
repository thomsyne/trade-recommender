"""Inspect persisted development decisions; never evaluate them against prices."""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path

from market.state.canonical import canonical_json, identity_digest
from research.validation_reconciliation import MONEY, SCENARIOS, require


def scan(path, frozen):
    """Bounded sequential read. Reject nondevelopment catalogs before body reads."""
    registration, rid = frozen["body"], frozen["identity"]
    require(rid == identity_digest(registration), "registration_identity")
    require(
        datetime.fromisoformat(registration["development"][1])
        <= datetime.fromisoformat("2025-01-06T00:00:00+00:00"),
        "sealed_registration_period",
    )
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        tables = {
            r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        require(tables == {"registration", "checkpoint"}, "not_an_evidence_catalog")
        saved = connection.execute(
            "SELECT body FROM registration WHERE identity=?", (rid,)
        ).fetchone()
        require(saved is not None and json.loads(saved[0]) == registration, "catalog_registration")
        # Authorized sealed-presence control: only registration/count/period bounds.
        bounds = connection.execute("""SELECT registration_id, count(*),
            min(json_extract(body,'$.key.start')), max(json_extract(body,'$.key.end'))
            FROM checkpoint GROUP BY registration_id""").fetchall()
        require(
            all(
                registration["development"][0] <= r[2] < r[3] <= registration["development"][1]
                for r in bounds
            ),
            "nondevelopment_catalog",
        )
        chains, selected, digest_list = {}, {}, []
        for identity, text, digest in connection.execute(
            "SELECT identity,body,body_sha256 FROM checkpoint WHERE registration_id=? ORDER BY rowid",
            (rid,),
        ):
            body = json.loads(text)
            key = body["key"]
            pair = key["strategy"], key["instrument"]
            require(key["registration"] == body["registration"] == rid, "checkpoint_registration")
            require(
                identity == identity_digest(key) and digest == identity_digest(body),
                "checkpoint_hash",
            )
            day, end = datetime.fromisoformat(key["start"]), datetime.fromisoformat(key["end"])
            require(
                day.utcoffset() == timedelta(0) and end - day == timedelta(days=1),
                "checkpoint_UTC_day",
            )
            chain = chains.setdefault(
                pair,
                {
                    "end": registration["development"][0],
                    "digest": None,
                    "count": 0,
                    "rows": 0,
                    "active": dict.fromkeys(SCENARIOS),
                },
            )
            require(
                key["start"] == chain["end"] and body["predecessor"] == chain["digest"],
                "checkpoint_chronology",
            )
            seen = set()
            for row in body["rows"]:
                require((row["strategy"], row["instrument"]) == pair, "row_attribution")
                at = datetime.fromisoformat(row["opportunity"])
                require(
                    day <= at < end and at.utcoffset() == timedelta(0) and at not in seen,
                    "row_chronology",
                )
                seen.add(at)
                output = row["decision"]
                require(
                    row["evaluation_identity"]
                    == identity_digest(
                        {
                            "registration": rid,
                            "opportunity": row["opportunity"],
                            "instrument": pair[1],
                            "strategy": pair[0],
                            "decision": output,
                        }
                    ),
                    "evaluation_hash",
                )
                setup = next(
                    (p for p in output.get("outputs", []) if p["schema"] == "phase5/setup-v1"), None
                )
                require(set(row["scenarios"]) == set(SCENARIOS), "row_scenarios")
                for scenario, result in row["scenarios"].items():
                    active = chain["active"][scenario]
                    if active and at < datetime.fromisoformat(active):
                        require(
                            result == {"state": "occupied", "reason": "prior_position_active"},
                            "occupancy",
                        )
                        continue
                    if setup is None:
                        reason = output.get("reason") or output["outputs"][0]["reason"]
                        state = (
                            "no_setup"
                            if reason
                            in {
                                "no_confirmation_before_expiry",
                                "no_aligned_deviation",
                                "no_qualified_pullback",
                                "no_unique_confirmed_failed_break",
                            }
                            else "unavailable"
                        )
                        require(result == {"state": state, "reason": reason}, "decision_state")
                        continue
                    require(result["state"] in {"modeled", "unavailable"}, "setup_state")
                    chain["active"][scenario] = result.get("exited_at", setup["exit_at"])
                    if result["state"] != "modeled":
                        require(set(result) == {"state", "reason"}, "unavailable_result")
                        continue
                    require(
                        result["registration_sha256"] == rid
                        and result["identity"]
                        == identity_digest(
                            {
                                "setup": setup,
                                "instrument": pair[1],
                                "scenario": scenario,
                                "result": {k: v for k, v in result.items() if k != "identity"},
                            }
                        ),
                        "result_hash",
                    )
                    with localcontext() as ctx:
                        ctx.prec = 34
                        # Match the explicitly registered operation order, not a tolerance.
                        net = D(result["gross_CAD"]) - D(result["spread_CAD"])
                        net -= D(result["slippage_CAD"])
                        net -= D(result["commission_CAD"])
                        net -= D(result["conversion_CAD"])
                        require(
                            D(result["financing_CAD"]) == 0
                            and result["financing_basis"] == "no_rollover_touched",
                            "financing_basis",
                        )
                        require(net == D(result["net_CAD"]), "gross_cost_net")
                        require(
                            net / D(registration["research_equity_CAD"])
                            == D(result["net_account_return"]),
                            "return_denominator",
                        )
                    entry, exit = map(
                        datetime.fromisoformat, (result["entered_at"], result["exited_at"])
                    )
                    require(
                        at <= entry < exit <= datetime.fromisoformat(registration["development"][1])
                        and result["holding_seconds"] == int((exit - entry).total_seconds()),
                        "result_chronology",
                    )
                    require(
                        result["direction"] == setup["direction"] and D(result["units"]) > 0,
                        "result_direction_units",
                    )
                    require(
                        all(
                            D(result[f]).is_finite()
                            and (f in {"gross_CAD", "net_CAD"} or D(result[f]) >= 0)
                            for f in MONEY
                        ),
                        "result_money",
                    )
                # Only setup opportunities can contribute an overlay difference.
                # Preserve complete opportunity keys, decision and result digests;
                # omit prices and bulky input payloads from the private receipt.
                if setup:
                    rkey = "|".join((*pair, row["opportunity"]))
                    selected[rkey] = {
                        "decision": identity_digest(output),
                        "overlays": row["overlays"],
                        "volatility_stratum": row["volatility_stratum"],
                        "scenarios": {
                            s: {
                                k: v
                                for k, v in r.items()
                                if k not in {"identity", "registration_sha256"}
                            }
                            for s, r in row["scenarios"].items()
                        },
                    }
                chain["rows"] += 1
            require(body["end_state"] == chain["active"], "end_state")
            chain.update(end=key["end"], digest=digest, count=chain["count"] + 1)
            digest_list.append((identity, digest))
        return {
            "catalog": Path(path).name,
            "registration": rid,
            "chains": [
                {"strategy": p[0], "instrument": p[1], **c} for p, c in sorted(chains.items())
            ],
            "checkpoints": len(digest_list),
            "manifest": identity_digest(sorted(digest_list)),
            "setup_rows": selected,
            "scope": "stored_decision_state_accounting_and_ancestry_not_price_replay",
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("registration", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = scan(args.catalog, json.loads(args.registration.read_text()))
    with args.output.open("x") as handle:
        handle.write(canonical_json(result) + "\n")
    args.output.chmod(0o600)
    print(
        canonical_json(
            {
                "catalog": result["catalog"],
                "checkpoints": result["checkpoints"],
                "setup_rows": len(result["setup_rows"]),
                "chain_lengths": dict(Counter(str(c["count"]) for c in result["chains"])),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
