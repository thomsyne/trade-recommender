"""Immutable offline validation revisions, not original prospective Phase5 rows."""

import hashlib
import json
import os
import platform
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from zoneinfo import TZPATH

from market.state.canonical import canonical_json, identity_digest
from market.strategy.definitions import (
    STRATEGIES,
    definition_digest,
    simulator_definition,
    verify_implementation,
)
from research.validation_acquisition import ROOT, canonical_pairs
from research.validation_audit import PERIODS

VALIDATION_REVISION = 3
SOURCE_FILES = (
    *(str(path.relative_to(ROOT)) for path in sorted((ROOT / "market/state").glob("*.py"))),
    "market/apps.py",
    "market/models.py",
    "market/quality.py",
    "research/validation_data.py",
    "research/validation_registration.py",
    "research/validation_replay.py",
    "research/validation_execution.py",
    "research/validation_batch.py",
    "research/validation_reports.py",
    "docs/phase5.5/validation-contract.md",
    "docs/phase5.5/validation-revision-2.md",
    "docs/phase5.5/frozen-registration.json",
    "docs/phase5.5/frozen-registration-v2.json",
    "docs/phase5.5/sealed-manifest.json",
    "docs/phase5.5/correction-cycle.md",
)
SCENARIOS = ("baseline", "adverse_cost", "extra_interval_latency")
DEVELOPMENT = ("2019-01-07T00:00:00+00:00", "2025-01-06T00:00:00+00:00")
DEVELOPMENT_SPLIT = "2022-01-03T00:00:00+00:00"


def sources():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def runtime():
    packages = {}
    for name in (
        "arch",
        "numpy",
        "scipy",
        "pandas",
        "statsmodels",
        "formulaic",
        "patsy",
        "packaging",
        "python-dateutil",
        "pytz",
        "tzdata",
        "Django",
        "httpx",
    ):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unavailable"
    zones = {}
    for zone in ("America/New_York", "Europe/London"):
        paths = [Path(root) / zone for root in TZPATH if (Path(root) / zone).is_file()]
        if not paths:
            raise ValueError("timezone_source_unavailable")
        zones[zone] = hashlib.sha256(paths[0].read_bytes()).hexdigest()
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": packages,
        "single_thread_numeric_runtime": {
            name: os.environ.get(name) == "1"
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "regular_model_timezone_sha256": zones,
        "historical_exception_vintage": "unavailable",
    }


def contract(audit):
    verify_implementation()
    if (
        audit.get("schema") != "phase55/acquired-coverage-v1"
        or audit.get("holdout") != "sealed_metadata_only"
    ):
        raise ValueError("coverage_audit_required")
    population = canonical_pairs()
    expected = {
        (period, pair, granularity)
        for period, _, _ in PERIODS
        for pair in population
        for granularity in ("W", "D", "H4", "H1", "M15")
    }
    actual = {(g["period"], g["instrument"], g["granularity"]) for g in audit["groups"]}
    if expected != actual or len(audit["groups"]) != len(expected):
        raise ValueError("coverage_population_mismatch")
    for group in audit["groups"]:
        if group["duplicate_intervals"] or group["unexpected_regular_open_intervals"]:
            raise ValueError("coverage_interval_integrity")
        # Outcome-blind minimum raw coverage, not a waiver of any local gap.
        if (group["rows"] - group["outside_regular_model_intervals"]) * 100 < group[
            "nominal_expected_intervals"
        ] * 95:
            raise ValueError("coverage_below_preregistered_95_percent")
        if group["period"] == "warmup" and group["granularity"] == "D" and group["rows"] < 192:
            raise ValueError("daily_warmup_insufficient")
    return {
        "schema": "phase55/validation-registration-v1",
        "revision": VALIDATION_REVISION,
        "supersedes_registration": json.loads(
            (ROOT / "docs/phase5.5/frozen-registration-v2.json").read_text()
        )["identity"],
        "mode": "model_based_retrospective_regular_session_not_broker_execution",
        "strategies": {
            s: {
                "definition_sha256": definition_digest(s),
                "simulator_sha256": identity_digest(simulator_definition(s)),
            }
            for s in STRATEGIES
        },
        "instruments": population,
        "periods": PERIODS,
        "development": DEVELOPMENT,
        "development_split": DEVELOPMENT_SPLIT,
        "holdout_access": "sealed",
        "audit_sha256": identity_digest(audit),
        "acquisition_registration": audit["acquisition_registration"],
        "manifest": audit["manifest"],
        "runner_sources": sources(),
        "runtime": runtime(),
        "scenarios": SCENARIOS,
        "mandatory_unavailable": audit["mandatory_unavailable"],
        "prior_use": audit["prior_use"],
        "account_currency": "CAD",
        "commission_CAD_per_base_side": {
            "baseline": "0.0001",
            "adverse_cost": "0.0002",
            "extra_interval_latency": "0.0001",
        },
        "slippage_spreads_per_side": {
            "baseline": "1",
            "adverse_cost": "2",
            "extra_interval_latency": "1",
        },
        "risk_fraction": "0.005",
        "notional_cap_equity": "1",
        "research_equity_CAD": "100000",
        "dependence": "UTC_ISO_week_shared_currency_overlap",
        "min_effective_weeks": 52,
        "min_half_weeks": 20,
        "min_opportunities": 100,
        "min_trades": 30,
        "minimum_instruments": 3,
        "maximum_absolute_net_concentration": "0.5",
        "robustness": [
            "adverse_cost",
            "extra_interval_latency",
            "remove_best_instrument",
            "remove_best_UTC_month",
            "halves",
            "long_short",
            "sessions",
            "high_vol",
            "event_periods_unavailable",
            "missingness",
            "adverse_gap_dual_hit",
        ],
        "report_schema": "phase55/validation-report-v2",
        "activation": "forbidden",
        "shadow": {
            "start": "2026-09-11T00:00:00+00:00",
            "minimum_end": "2026-11-06T00:00:00+00:00",
            "maximum_end": "2026-12-04T00:00:00+00:00",
            "mode": "offline_only",
        },
    }


def validate_registration(body):
    # Admission binds every field, not merely the formula/population subset.
    audit = json.loads((ROOT / "docs/phase5.5/acquired-coverage.json").read_text())
    if canonical_json(body) != canonical_json(contract(audit)):
        raise ValueError("validation_registration_drift")


def admit_period(body, start, end):
    validate_registration(body)
    if any(t.utcoffset() != timedelta(0) for t in (start, end)) or start >= end:
        raise ValueError("validation_period_invalid")
    a, b = map(datetime.fromisoformat, DEVELOPMENT)
    if not a <= start < end <= b:
        raise ValueError("sealed_or_unregistered_period")


class Catalog:
    """Local append-only artifact catalog; no production ORM or consumer hooks.

    SQL calls the same admission check as Python. Plain SQLite connections cannot
    insert without registering the validator; the file is an owner-private artifact,
    not a security boundary against its OS owner (nor is a superuser-owned PG DB).
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.acquisition_path = ROOT / ".candidate-data/phase55-v1/acquisition.sqlite3"
        # In-memory proofs originate only in deterministic replay, never in
        # persisted claims. They survive neither process restart nor source drift.
        self._proofs = {}
        self._pending = None
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.create_function(
            "digest", 1, lambda body: identity_digest(json.loads(body)), deterministic=True
        )
        self.db.create_function("admit", 1, self._admit, deterministic=True)
        self.db.create_function("admit_checkpoint", 2, self._admit_checkpoint)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS registration (
                identity TEXT PRIMARY KEY, body TEXT NOT NULL CHECK(json_valid(body)),
                registered_at TEXT NOT NULL, CHECK(identity=digest(body)), CHECK(admit(body)=1));
            CREATE TABLE IF NOT EXISTS checkpoint (
                identity TEXT PRIMARY KEY, registration_id TEXT NOT NULL REFERENCES registration(identity),
                body TEXT NOT NULL CHECK(json_valid(body)), body_sha256 TEXT NOT NULL,
                CHECK(body_sha256=digest(body)),
                CHECK(json_extract(body,'$.schema')='phase55/checkpoint-v1'),
                CHECK(json_extract(body,'$.registration')=registration_id));
            CREATE INDEX IF NOT EXISTS checkpoint_population ON checkpoint(
                registration_id, json_extract(body,'$.key.strategy'),
                json_extract(body,'$.key.instrument'), json_extract(body,'$.key.start'));
            CREATE TRIGGER IF NOT EXISTS checkpoint_identity BEFORE INSERT ON checkpoint BEGIN
                SELECT CASE WHEN NEW.identity != digest(json_extract(NEW.body,'$.key'))
                    THEN RAISE(ABORT,'checkpoint_identity_mismatch') END;
                SELECT CASE WHEN admit_checkpoint(NEW.body,
                    (SELECT body FROM registration WHERE identity=NEW.registration_id)) != 1
                    THEN RAISE(ABORT,'checkpoint_admission') END;
            END;
        """)
        for table in ("registration", "checkpoint"):
            for action in ("UPDATE", "DELETE"):
                self.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_validation'); END"
                )

    @staticmethod
    def _admit(text):
        try:
            validate_registration(json.loads(text))
            return 1
        except (ValueError, TypeError, KeyError, OSError):
            return 0

    def _admit_checkpoint(self, text, registration_text):
        try:
            from market.strategy.schema import validate_evaluation
            from research.validation_batch import BLOCKED, OVERLAYS, opportunities
            from research.validation_reports import MONEY

            body, registration = json.loads(text), json.loads(registration_text)
            key = body["key"]
            if set(body) != {"schema", "registration", "key", "rows", "end_state", "predecessor"}:
                return 0
            if body["schema"] != "phase55/checkpoint-v1":
                return 0
            if set(key) != {"registration", "strategy", "instrument", "start", "end"}:
                return 0
            start, end = map(datetime.fromisoformat, (key["start"], key["end"]))
            a, b = map(datetime.fromisoformat, registration["development"])
            if (
                start.utcoffset() != timedelta(0)
                or end.utcoffset() != timedelta(0)
                or start.time() != datetime.min.time()
                or end - start != timedelta(days=1)
                or not a <= start < end <= b
                or key["strategy"] not in registration["strategies"]
                or key["instrument"] not in registration["instruments"]
                or body["registration"] != key["registration"]
                or key["registration"] != identity_digest(registration)
                or type(body["rows"]) is not list
                or len(body["rows"]) > 2000
                or set(body["end_state"]) != set(registration["scenarios"])
            ):
                return 0
            for at in body["end_state"].values():
                if at is not None and datetime.fromisoformat(at).utcoffset() != timedelta(0):
                    return 0
            seen = set()
            for row in body["rows"]:
                at = datetime.fromisoformat(row["opportunity"])
                if (
                    not start <= at < end
                    or at in seen
                    or row["strategy"] != key["strategy"]
                    or row["instrument"] != key["instrument"]
                    or set(row["scenarios"]) != set(registration["scenarios"])
                    or any(
                        r["state"] not in {"unavailable", "no_setup", "occupied", "modeled"}
                        for r in row["scenarios"].values()
                    )
                ):
                    return 0
                if set(row) != {
                    "opportunity",
                    "strategy",
                    "instrument",
                    "session",
                    "decision",
                    "scenarios",
                    "evaluation_identity",
                    "overlays",
                    "volatility_stratum",
                }:
                    return 0
                if row["session"] != (
                    key["strategy"].split(":")[1] if ":" in key["strategy"] else "regular_fx"
                ):
                    return 0
                decision = row["decision"]
                if key["strategy"] in BLOCKED:
                    if decision != {
                        "schema": "phase55/readiness-v1",
                        "reason": BLOCKED[key["strategy"]],
                    }:
                        return 0
                else:
                    validate_evaluation(decision, key["strategy"])
                if row["evaluation_identity"] != identity_digest(
                    {
                        "registration": key["registration"],
                        "opportunity": row["opportunity"],
                        "instrument": key["instrument"],
                        "strategy": key["strategy"],
                        "decision": decision,
                    }
                ):
                    return 0
                if set(row["overlays"]) != set(OVERLAYS) or row["volatility_stratum"] not in {
                    "high",
                    "other",
                    "unavailable",
                }:
                    return 0
                if row["overlays"]["macro-risk-v1"] != {
                    "multiplier": None,
                    "reason": BLOCKED["macro-risk-v1"],
                }:
                    return 0
                for risk in row["overlays"].values():
                    value = risk["multiplier"]
                    if value is not None and (not D(value).is_finite() or not 0 <= D(value) <= 1):
                        return 0
                for scenario, result in row["scenarios"].items():
                    if not isinstance(result.get("reason"), str) or not result["reason"]:
                        return 0
                    if result["state"] != "modeled":
                        if set(result) != {"state", "reason"}:
                            return 0
                        continue
                    setup = next(
                        (
                            p
                            for p in decision.get("outputs", [])
                            if p["schema"] == "phase5/setup-v1"
                        ),
                        None,
                    )
                    if (
                        setup is None
                        or result["registration_sha256"] != key["registration"]
                        or result["identity"]
                        != identity_digest(
                            {
                                "setup": setup,
                                "instrument": key["instrument"],
                                "scenario": scenario,
                                "result": {k: v for k, v in result.items() if k != "identity"},
                            }
                        )
                        or any(
                            not D(result[field]).is_finite()
                            for field in MONEY + ("units", "net_account_return")
                        )
                        or D(result["units"]) <= 0
                        or any(
                            D(result[field]) < 0
                            for field in MONEY
                            if field not in {"gross_CAD", "net_CAD"}
                        )
                        or not a
                        <= datetime.fromisoformat(result["entered_at"])
                        < datetime.fromisoformat(result["exited_at"])
                        <= b
                    ):
                        return 0
                seen.add(at)

            if key["strategy"] in OVERLAYS or seen != set(opportunities(key["strategy"], start)):
                return 0
            digest = identity_digest(body)
            proof = self._proofs.get(identity_digest(key))
            if self._pending == digest and proof is not None:
                if proof[1] != digest or proof[0] != body["predecessor"]:
                    return 0
                if start == a:
                    return int(body["predecessor"] is None)
                prior_key = {
                    **key,
                    "start": (start - timedelta(days=1)).isoformat(),
                    "end": key["start"],
                }
                prior = self.db.execute(
                    "SELECT body,body_sha256 FROM checkpoint WHERE identity=?",
                    (identity_digest(prior_key),),
                ).fetchone()
                return int(
                    prior is not None
                    and identity_digest(json.loads(prior[0])) == prior[1] == body["predecessor"]
                )
            # Raw SQL has the same semantic boundary as the Python API. Rehashed
            # accounting, altered decisions and invented occupancy cannot pass.
            self.load(key["registration"])
            _, active, predecessor = self.verify_chain(
                key["registration"], key["strategy"], key["instrument"], stop=start, collect=False
            )
            expected = self.replay_checkpoint(key, registration, active, predecessor)
            return int(canonical_json(expected) == canonical_json(body))
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            return 0

    def replay_checkpoint(self, key, registration, active, predecessor):
        """Derive the closed decision/result/accounting/state contract from inputs."""
        from research.validation_batch import OVERLAYS, data_for, day_rows

        if set(key) != {"registration", "strategy", "instrument", "start", "end"}:
            raise ValueError("checkpoint_key_contract")
        start, end = map(datetime.fromisoformat, (key["start"], key["end"]))
        a, b = map(datetime.fromisoformat, registration["development"])
        if (
            key["registration"] != identity_digest(registration)
            or key["strategy"] not in registration["strategies"]
            or key["strategy"] in OVERLAYS
            or key["instrument"] not in registration["instruments"]
            or start.utcoffset() != timedelta(0)
            or end.utcoffset() != timedelta(0)
            or start.time() != datetime.min.time()
            or end - start != timedelta(days=1)
            or not a <= start < end <= b
        ):
            raise ValueError("checkpoint_sealed_population_or_period")
        if start == a:
            valid_state = predecessor is None and active == {
                s: None for s in registration["scenarios"]
            }
        else:
            prior_key = {
                **key,
                "start": (start - timedelta(days=1)).isoformat(),
                "end": key["start"],
            }
            proof = self._proofs.get(identity_digest(prior_key))
            valid_state = (
                proof is not None and proof[1] == predecessor and proof[2] == canonical_json(active)
            )
        if not valid_state:
            raise ValueError("resume_state_not_derived_from_verified_prefix")
        data, conversions = data_for(
            self.acquisition_path, registration, key["strategy"], key["instrument"]
        )
        state = dict(active)
        rows = day_rows(
            key["registration"],
            registration,
            key["strategy"],
            key["instrument"],
            start,
            data,
            conversions,
            state,
        )
        body = {
            "schema": "phase55/checkpoint-v1",
            "registration": key["registration"],
            "key": dict(key),
            "rows": rows,
            "end_state": state,
            "predecessor": predecessor,
        }
        # Store only replay-derived hashes/state, not a supplied row's signature.
        self._proofs[identity_digest(key)] = (
            predecessor,
            identity_digest(body),
            canonical_json(state),
        )
        return body

    def verify_chain(self, registration_id, strategy, instrument, *, stop=None, collect=True):
        """Verify a complete causal prefix before exposing rows or resume state.

        Traversal follows the fixed daily grid, not arbitrary ancestor pointers.
        Fetching completes before replay so a reader does not hold a DB lock while
        evaluating formulas. A fresh call always hashes the actual stored bodies.
        """
        from research.validation_batch import OVERLAYS

        registration = self.load(registration_id)
        start, end = map(datetime.fromisoformat, registration["development"])
        stop = end if stop is None else stop
        if (
            strategy not in registration["strategies"]
            or strategy in OVERLAYS
            or instrument not in registration["instruments"]
            or stop.utcoffset() != timedelta(0)
            or stop.time() != datetime.min.time()
            or not start <= stop <= end
        ):
            raise ValueError("chain_sealed_population_or_period")
        if (
            stop == end
            and self.db.execute(
                """SELECT count(*) FROM checkpoint WHERE registration_id=?
            AND json_extract(body,'$.key.strategy')=? AND json_extract(body,'$.key.instrument')=?""",
                (registration_id, strategy, instrument),
            ).fetchone()[0]
            != (end - start).days
        ):
            raise ValueError("complete_population_incomplete_or_extra_period")
        records = self.db.execute(
            """SELECT identity,body,body_sha256 FROM checkpoint
            WHERE registration_id=? AND json_extract(body,'$.key.strategy')=?
            AND json_extract(body,'$.key.instrument')=? AND json_extract(body,'$.key.start')<?
            ORDER BY json_extract(body,'$.key.start') LIMIT ?""",
            (registration_id, strategy, instrument, stop.isoformat(), (stop - start).days + 1),
        ).fetchall()
        if len(records) != (stop - start).days:
            raise ValueError("previous_checkpoint_required_chain_incomplete")
        active, predecessor, rows = {s: None for s in registration["scenarios"]}, None, []
        day = start
        for identity, text, digest in records:
            body = json.loads(text)
            key = {
                "registration": registration_id,
                "strategy": strategy,
                "instrument": instrument,
                "start": day.isoformat(),
                "end": (day + timedelta(days=1)).isoformat(),
            }
            if (
                identity_digest(key) != identity
                or body.get("key") != key
                or identity_digest(body) != digest
                or body.get("predecessor") != predecessor
            ):
                raise ValueError("checkpoint_chain_identity_or_ancestry")
            proof = self._proofs.get(identity)
            if proof is None or proof[0] != predecessor:
                self.replay_checkpoint(key, registration, active, predecessor)
                proof = self._proofs[identity]
            if proof[1] != digest or canonical_json(body.get("end_state")) != proof[2]:
                raise ValueError("checkpoint_semantic_replay_mismatch")
            active = json.loads(proof[2])
            predecessor = digest
            if collect:
                rows.extend(body["rows"])
            day += timedelta(days=1)
        return rows, active, predecessor

    def register(self, audit):
        body = json.loads(canonical_json(contract(audit)))
        validate_registration(body)
        identity = identity_digest(body)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO registration VALUES (?,?,?)",
                (identity, canonical_json(body), datetime.now(UTC).isoformat()),
            )
        return identity, body

    def load(self, identity):
        row = self.db.execute(
            "SELECT body FROM registration WHERE identity=?", (identity,)
        ).fetchone()
        if row is None or identity_digest(json.loads(row[0])) != identity:
            raise ValueError("registration_missing_or_corrupt")
        body = json.loads(row[0])
        validate_registration(body)
        return body

    def checkpoint(self, key, rows, *, end_state, predecessor):
        body = {
            "schema": "phase55/checkpoint-v1",
            "registration": key["registration"],
            "key": key,
            "rows": rows,
            "end_state": dict(end_state),
            "predecessor": predecessor,
        }
        # The batch authenticates source/runtime/manifest before any data access.
        # SQL independently admits every insert against the immutable registered
        # periods, population, row schema and predecessor, without rereading all
        # source files and package metadata for each daily checkpoint.
        if (
            key["strategy"] not in STRATEGIES
            or key["instrument"] not in canonical_pairs()
            or len(rows) > 2000
        ):
            raise ValueError("checkpoint_population_or_bound")
        registration = self.load(key["registration"])
        _, active, prior = self.verify_chain(
            key["registration"],
            key["strategy"],
            key["instrument"],
            stop=datetime.fromisoformat(key["start"]),
            collect=False,
        )
        expected = self.replay_checkpoint(key, registration, active, prior)
        if canonical_json(expected) != canonical_json(body):
            raise sqlite3.IntegrityError("checkpoint_semantic_replay_mismatch")
        return self._write_replayed(body)

    def _write_replayed(self, body):
        """Internal producer path; SQL still requires the replay-derived proof."""
        key = body["key"]
        identity = identity_digest(key)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT body FROM checkpoint WHERE identity=?", (identity,)
            ).fetchone()
            if prior and prior[0] != canonical_json(body):
                raise ValueError("checkpoint_retry_conflict")
            self._pending = identity_digest(body)
            self.db.execute(
                "INSERT OR IGNORE INTO checkpoint VALUES (?,?,?,?)",
                (identity, key["registration"], canonical_json(body), identity_digest(body)),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._pending = None
        return identity

    def close(self):
        self.db.close()
