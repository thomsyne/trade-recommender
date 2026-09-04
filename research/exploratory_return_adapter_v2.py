"""Django persistence boundary for the v2 exploratory-return runner.

This module is imported only after a future fixed-path execution authorization
has passed.  It contains no provider or network client.  The adapter projects
sealed registered candles into the exact pure-calculator schema in bounded,
set-oriented ORM queries; it never performs per-event candle queries.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from contextlib import contextmanager
from datetime import UTC, timedelta
from decimal import Decimal

from django.db import connection, transaction

from market.models import (
    Candle,
    CandleConflict,
    DatasetVersion,
    HistoricalIngestionAttempt,
    HistoricalTimestampObservation,
    IngestionRun,
)
from market.quality import registered_candle_completion
from research import exploratory_returns_v2 as calculator
from research import failed_break_v2_s1_outcome as s1_outcome
from research import s2_geometry_v2, s2_policy_v2
from research.models import EntryEligibilityEvaluation, JobRun, SetupTransition, StrategyVersion

from .exploratory_return_runner_v2 import IDEMPOTENCY_KEY, JOB_IDENTITY, RunnerRefusal, require

DATASET_NAME = "failed-break-provider-observed-historical"
DATASET_VERSION = "phase-2b1r-v2"
STRATEGY_VERSION = "failed-break-phase-1-admission-correction-v2"
S1_JOB = "failed-break-signal-count-s1-v2"
PIP_SIZE = {"USD_JPY": "0.01"}


def _stamp(value):
    return value.isoformat()


def _midpoint(bid, ask):
    return str((Decimal(bid) + Decimal(ask)) / 2)


class DjangoSealedEvidenceAdapter:
    """Set-oriented registered-candle adapter; no caller-selectable fields."""

    def __init__(self):
        self.query_counts = {}
        self._dataset = None
        self._strategy = None
        self._geometry = None

    def _observe(self, phase, before):
        self.query_counts[phase] = len(connection.queries) - before

    def _require_database_identity(self):
        """Keep the persistent adapter fixed to the local research database."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), inet_server_addr()")
            require(
                cursor.fetchone() == ("trade_recommender_research", None),
                "exact local research database required",
            )

    def verify_return_blind_lineage(self) -> dict:
        before = len(connection.queries)
        self._require_database_identity()
        s1 = s1_outcome.load_v2_s1_outcome_acceptance()
        policy = s2_policy_v2.load_policy()
        self._geometry = s2_geometry_v2.verify_committed()
        job, s0_job, dataset, strategy = s1_outcome.select_persistent_v2_s1_evidence()
        require(
            (dataset.pk, strategy.pk, s0_job.pk, job.pk) == (3, 2, 4, 5),
            "accepted operational anchors changed",
        )
        dataset = DatasetVersion.objects.select_related(
            "registration", "registration__data_contract"
        ).get(pk=dataset.pk)
        binding = s1["bindings"]
        require(
            dataset.manifest_sha256 == binding["dataset"]["manifest_sha256"]
            and dataset.data_contract_sha256 == binding["dataset"]["contract_sha256"]
            and dataset.registration.configuration_sha256
            == binding["dataset"]["registration_configuration_sha256"]
            and dataset.registration.report_sha256
            == binding["dataset"]["registration_report_sha256"]
            and dataset.registration.data_contract.identity
            == binding["dataset"]["effective_data_identity"],
            "registered dataset lineage changed",
        )
        require(
            strategy.detector_version == binding["strategy"]["detector_identity"]
            and strategy.data_identity == binding["dataset"]["effective_data_identity"]
            and strategy.content_hash == binding["strategy"]["content_sha256"],
            "strategy lineage changed",
        )
        require(
            job.config_hash == s1["execution"]["configuration_sha256"]
            and job.evidence["report"]["report_sha256"] == s1["execution"]["report_sha256"],
            "accepted S1 evidence changed",
        )
        require(
            s0_job.job_name == binding["s0"]["job_identity"]
            and s0_job.config_hash == binding["s0"]["configuration_sha256"]
            and s0_job.evidence["report"]["report_sha256"] == binding["s0"]["report_sha256"],
            "accepted S0 evidence changed",
        )
        require(
            s1_outcome._application_state() == s1["application_state"],
            "database is not the exact accepted pristine pre-return state",
        )
        attempts = HistoricalIngestionAttempt.objects.filter(chunk__dataset_version=dataset)
        require(
            attempts.count() == 132
            and attempts.filter(
                attempt_number=1,
                ingestion_run__status=IngestionRun.Status.SUCCEEDED,
                ingestion_run__rejected_count=0,
            ).count()
            == 132,
            "successful attempt-1 acquisition evidence changed",
        )
        require(
            not JobRun.objects.filter(job_name=JOB_IDENTITY).exists(),
            "exploratory return evidence already exists",
        )
        self._dataset, self._strategy = dataset, strategy
        self._observe("return_blind_lineage", before)
        return {
            "dataset_version": dataset.version,
            "strategy_version": strategy.version,
            "s1_outcome": "ACCEPTED",
            "s2_policy": policy["status"],
            "promotion_permanently_prohibited": policy["boundary"][
                "promotion_permanently_prohibited"
            ],
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "s1_report_sha256": s1["execution"]["report_sha256"],
        }

    @staticmethod
    def _prior_start(starts, completions, when):
        index = bisect_left(completions, when) - 1
        require(index >= 0, "no strictly prior sealed H1 conversion member")
        return starts[index]

    def load_normalized_events(
        self, expected_keys: tuple[str, ...], *, progress=None
    ) -> list[dict]:
        require(self._dataset is not None and self._geometry is not None, "lineage not verified")
        before = len(connection.queries)
        geometry_events = self._geometry["events"]
        require(
            tuple(sorted(row["physical_key"] for row in geometry_events))
            == tuple(sorted(expected_keys)),
            "geometry event set changed",
        )
        if progress:
            progress("cohort_reconstruction", len(geometry_events), 82)
        setup_ids = [row["setup_id"] for row in geometry_events]
        evaluations = list(
            EntryEligibilityEvaluation.objects.select_related("setup", "setup__instrument")
            .filter(
                setup_id__in=setup_ids,
                decision=EntryEligibilityEvaluation.Decision.ENTRY_PENDING,
                setup__dataset_version=self._dataset,
                setup__strategy_version=self._strategy,
            )
            .values(
                "id",
                "setup_id",
                "book_identity",
                "entry_timestamp",
                "entry_price",
                "stop_price",
                "target_price",
                "risk_per_unit_cad",
                "evidence_hash",
                "setup__instrument__code",
                "setup__direction",
            )
        )
        confirmations = {
            row["setup_id"]: row
            for row in SetupTransition.objects.filter(
                setup_id__in=setup_ids,
                from_state=SetupTransition.State.TRIGGER_PENDING,
                to_state=SetupTransition.State.CONFIRMED,
                book_identity="",
                dataset_version=self._dataset,
                strategy_version=self._strategy,
            ).values("setup_id", "effective_at", "evidence", "evidence_hash")
        }
        by_setup = {}
        for row in evaluations:
            by_setup.setdefault(row["setup_id"], []).append(row)
        require(len(by_setup) == 82 and len(evaluations) == 186, "entry evidence set changed")
        if progress:
            progress("entry_evidence", len(evaluations), 186)

        inventory_rows = HistoricalTimestampObservation.objects.filter(
            inventory__chunk__plan__registration__data_contract__identity=(
                "oanda-ba-ny17-friday-provider-observed-v2"
            ),
            inventory__chunk__granularity__in=("H1", "D"),
        ).values_list(
            "inventory__chunk__instrument__code",
            "inventory__chunk__granularity",
            "timestamp",
        )
        inventory = {}
        for code, granularity, timestamp in inventory_rows:
            inventory.setdefault((code, granularity), []).append(timestamp)
        inventory = {key: tuple(sorted(set(values))) for key, values in inventory.items()}
        require(len(inventory) == 12, "sealed D/H1 inventory incomplete")
        completion_inventory = {
            key: tuple(registered_candle_completion(value, key[1]) for value in starts)
            for key, starts in inventory.items()
        }
        if progress:
            progress("sealed_inventory", sum(map(len, inventory.values())), 362_229)

        needed = {}
        event_specs = []
        for geometry in geometry_events:
            rows = by_setup.get(geometry["setup_id"], [])
            require(rows, "missing entry evidence")
            first = rows[0]
            invariant = (
                "entry_timestamp",
                "entry_price",
                "stop_price",
                "target_price",
                "risk_per_unit_cad",
                "setup__instrument__code",
                "setup__direction",
            )
            require(
                all(all(row[field] == first[field] for field in invariant) for row in rows),
                "book-level entry evidence conflict",
            )
            require(
                sorted(row["book_identity"] for row in rows) == geometry["books"],
                "book membership changed",
            )
            expected_evaluations = sorted(
                (row["id"], row["book"], row["evidence_hash"]) for row in geometry["evaluations"]
            )
            observed_evaluations = sorted(
                (row["id"], row["book_identity"], row["evidence_hash"]) for row in rows
            )
            require(observed_evaluations == expected_evaluations, "entry evidence identity changed")
            code, entry = first["setup__instrument__code"], first["entry_timestamp"]
            horizon = calculator.timestamp(geometry["horizon_at"])
            h1_all, d_all = inventory[(code, "H1")], inventory[(code, "D")]
            left, right = bisect_left(h1_all, entry), bisect_right(h1_all, horizon)
            h1_starts = h1_all[left:right]
            d_all_completions = completion_inventory[(code, "D")]
            d_left = bisect_right(d_all_completions, entry)
            d_right = bisect_right(d_all_completions, horizon)
            d_completions = d_all_completions[d_left:d_right]
            require(
                len(d_completions) >= 10 and h1_starts[-1] == horizon, "horizon inventory drift"
            )
            d_starts = d_all[d_left:d_right]
            needed.setdefault((code, "H1"), set()).update(h1_starts)
            needed.setdefault((code, "D"), set()).update(d_starts)
            confirmation = confirmations.get(geometry["setup_id"])
            require(confirmation is not None, "missing confirmation evidence")
            event_specs.append((geometry, first, h1_starts, d_completions, d_starts, confirmation))

            # Resolve every possible exit, rollover and daily-mark conversion
            # timestamp from ordered sealed inventory before price rows are read.
            decision_times = {entry, horizon}
            decision_times.update(start + timedelta(hours=1) for start in h1_starts)
            decision_times.update(value for value, _ in calculator._rollover_times(entry, horizon))
            mark = entry.astimezone(calculator.NY).replace(
                hour=17, minute=0, second=0, microsecond=0
            )
            while mark.astimezone(UTC) <= horizon:
                when = mark.astimezone(UTC)
                if when >= entry:
                    decision_times.add(when)
                    start = self._prior_start(
                        inventory[(code, "H1")],
                        completion_inventory[(code, "H1")],
                        when + timedelta(microseconds=1),
                    )
                    needed.setdefault((code, "H1"), set()).add(start)
                mark += timedelta(days=1)
            quote = code.split("_")[1]
            for when in decision_times:
                for pair, _direction in calculator.CAD_ROUTES[quote]:
                    start = self._prior_start(
                        inventory[(pair, "H1")],
                        completion_inventory[(pair, "H1")],
                        when,
                    )
                    needed.setdefault((pair, "H1"), set()).add(start)

        expected_candles = sum(len(values) for values in needed.values())
        if progress:
            progress("evidence_plan", expected_candles, expected_candles)
        candle_rows = self._load_candle_rows(needed, progress=progress)
        candle_map = {
            (row["instrument__code"], row["granularity"], row["timestamp"]): row
            for row in candle_rows
            if row["timestamp"] in needed.get((row["instrument__code"], row["granularity"]), ())
        }
        require(len(candle_map) == expected_candles, "missing sealed candle evidence")
        conflicts = set(
            CandleConflict.objects.filter(
                dataset_version=self._dataset,
                existing_candle_id__in=[row["id"] for row in candle_map.values()],
            ).values_list("existing_candle_id", flat=True)
        )
        require(not conflicts, "conflicting registered candle evidence")
        events = []
        for ordinal, spec in enumerate(event_specs, start=1):
            events.append(self._normalize_event(spec, inventory, completion_inventory, candle_map))
            if progress and (ordinal % 10 == 0 or ordinal == len(event_specs)):
                progress("normalization", ordinal, len(event_specs))
        self._observe("sealed_outcome_preload", before)
        return events

    def _load_candle_rows(self, needed, *, progress=None):
        """Load each governed instrument/granularity group in one indexed query."""

        candle_rows = []
        for ordinal, ((code, granularity), timestamps) in enumerate(
            sorted(needed.items()), start=1
        ):
            candle_rows.extend(
                Candle.objects.filter(
                    dataset_version=self._dataset,
                    instrument__code=code,
                    granularity=granularity,
                    timestamp__in=tuple(sorted(timestamps)),
                )
                .select_related("instrument")
                .values(
                    "id",
                    "instrument__code",
                    "granularity",
                    "timestamp",
                    "complete",
                    "bid_open",
                    "bid_high",
                    "bid_low",
                    "bid_close",
                    "ask_open",
                    "ask_high",
                    "ask_low",
                    "ask_close",
                )
            )
            if progress:
                progress("sealed_candles", ordinal, len(needed))
        return candle_rows

    def _candle(self, candle_map, code, granularity, start):
        row = candle_map.get((code, granularity, start))
        require(row is not None and row["complete"] is True, "missing sealed candle evidence")
        return row

    def _conversion(self, currency, when, inventory, completion_inventory, candles):
        legs = []
        for pair, direction in calculator.CAD_ROUTES[currency]:
            start = self._prior_start(
                inventory[(pair, "H1")], completion_inventory[(pair, "H1")], when
            )
            row = self._candle(candles, pair, "H1", start)
            legs.append(
                {
                    "pair": pair,
                    "direction": direction,
                    "completed_at": _stamp(registered_candle_completion(start, "H1")),
                    "midpoint_close": _midpoint(row["bid_close"], row["ask_close"]),
                    "sealed": True,
                    "complete": True,
                    "conflict": False,
                }
            )
        return {"currency": currency, "as_of": _stamp(when), "legs": legs}

    def _normalize_event(self, spec, inventory, completion_inventory, candles):
        geometry, evaluation, h1_starts, d_completions, d_starts, confirmation = spec
        code = geometry["instrument"]
        direction = geometry["direction"]
        entry = evaluation["entry_timestamp"]
        horizon = calculator.timestamp(geometry["horizon_at"])
        quote = code.split("_")[1]
        h1 = []
        for start in h1_starts:
            row = self._candle(candles, code, "H1", start)
            h1.append(
                {
                    "start": _stamp(start),
                    "sealed": True,
                    "complete": True,
                    "conflict": False,
                    **{
                        field: str(row[field])
                        for field in (
                            "bid_open",
                            "bid_high",
                            "bid_low",
                            "bid_close",
                            "ask_open",
                            "ask_high",
                            "ask_low",
                            "ask_close",
                        )
                    },
                }
            )
        daily = []
        for start, completed in zip(d_starts, d_completions, strict=True):
            row = self._candle(candles, code, "D", start)
            daily.append(
                {
                    "completed_at": _stamp(completed),
                    "sealed": True,
                    "complete": True,
                    "conflict": False,
                    "mid_close": _midpoint(row["bid_close"], row["ask_close"]),
                }
            )
        possible = {entry, horizon}
        possible.update(start + timedelta(hours=1) for start in h1_starts)
        rollover_times = calculator._rollover_times(entry, horizon)
        possible.update(value for value, _ in rollover_times)
        mark = entry.astimezone(calculator.NY).replace(hour=17, minute=0, second=0, microsecond=0)
        marks = []
        while mark.astimezone(UTC) <= horizon:
            when = mark.astimezone(UTC)
            if when >= entry:
                start = self._prior_start(
                    inventory[(code, "H1")],
                    completion_inventory[(code, "H1")],
                    when + timedelta(microseconds=1),
                )
                row = self._candle(candles, code, "H1", start)
                marks.append(
                    {
                        "at": _stamp(when),
                        "side_close": str(
                            row["bid_close"] if direction == "long" else row["ask_close"]
                        ),
                        "conversion": self._conversion(
                            quote, when, inventory, completion_inventory, candles
                        ),
                    }
                )
                possible.add(when)
            mark += timedelta(days=1)
        rollovers = []
        for when, multiplier in rollover_times:
            start = self._prior_start(
                inventory[(code, "H1")],
                completion_inventory[(code, "H1")],
                when + timedelta(microseconds=1),
            )
            row = self._candle(candles, code, "H1", start)
            rollovers.append(
                {
                    "at": _stamp(when),
                    "multiplier": multiplier,
                    "midpoint": _midpoint(row["bid_close"], row["ask_close"]),
                    "conversion": self._conversion(
                        quote, when, inventory, completion_inventory, candles
                    ),
                }
            )
        first = h1[0]
        governed_entry = first["ask_open"] if direction == "long" else first["bid_open"]
        require(
            all(
                evaluation[field] is not None
                for field in ("entry_price", "stop_price", "target_price", "risk_per_unit_cad")
            )
            and Decimal(governed_entry) == evaluation["entry_price"],
            "stored entry geometry changed",
        )
        require(
            confirmation["effective_at"] <= entry
            and confirmation["evidence_hash"] == geometry["confirmation_evidence_hash"],
            "confirmation lineage changed",
        )
        supporting = confirmation["evidence"].get("supporting_swing")
        require(supporting is not None, "supporting swing evidence missing")
        conversions = {
            _stamp(when): self._conversion(quote, when, inventory, completion_inventory, candles)
            for when in sorted(possible)
        }
        return {
            "physical_event_key": geometry["physical_key"],
            "books": geometry["books"],
            "instrument": code,
            "direction": direction,
            "entry_at": _stamp(entry),
            "horizon_at": _stamp(horizon),
            "entry_bid": first["bid_open"],
            "entry_ask": first["ask_open"],
            "stop": str(evaluation["stop_price"]),
            "target": str(evaluation["target_price"]),
            "supporting_swing": str(supporting),
            "pip_size": PIP_SIZE.get(code, "0.0001"),
            "risk_per_unit_cad": str(evaluation["risk_per_unit_cad"]),
            "expected_h1_starts": [_stamp(value) for value in h1_starts],
            "d_completions": [_stamp(value) for value in d_completions],
            "h1": h1,
            "daily": daily,
            "conversion": conversions,
            "rollovers": rollovers,
            "marks": marks,
        }


class DjangoResultStore:
    """One immutable JobRun row committed in the caller's atomic transaction."""

    def __init__(self):
        self.query_counts = {}

    def ensure_absent(self, idempotency_key):
        before = len(connection.queries)
        exists = JobRun.objects.filter(idempotency_key=idempotency_key).exists()
        self.query_counts["duplicate_check"] = len(connection.queries) - before
        require(not exists, "exploratory result already exists")

    @contextmanager
    def atomic(self):
        with transaction.atomic():
            yield

    def persist(self, payload, *, inject_failure_after=None):
        before = len(connection.queries)
        dataset = DatasetVersion.objects.get(name=DATASET_NAME, version=DATASET_VERSION)
        strategy = StrategyVersion.objects.get(version=STRATEGY_VERSION)
        job = JobRun.objects.create(
            job_name=JOB_IDENTITY,
            strategy_version=strategy,
            dataset_version=dataset,
            config_hash=payload["configuration_sha256"],
            idempotency_key=IDEMPOTENCY_KEY,
            as_of=calculator.timestamp("2019-01-01T05:00:00+00:00"),
            status=JobRun.Status.SUCCEEDED,
            evidence=payload,
        )
        if inject_failure_after == "insert":
            raise RunnerRefusal("injected failure after insert")
        stored = JobRun.objects.values_list("evidence", flat=True).get(pk=job.pk)
        require(stored == payload, "persistent readback changed")
        if inject_failure_after == "readback":
            raise RunnerRefusal("injected failure after readback")
        self.query_counts["result_persistence"] = len(connection.queries) - before
