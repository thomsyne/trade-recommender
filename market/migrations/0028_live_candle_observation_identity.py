"""Phase 1.4 — explicit live-candle observation identity and technical evidence versioning.

Live candles (``dataset_version`` NULL) previously accepted silent updates and
deletes at the database level, live ingestion ignored conflicting content, and
technical snapshots were updated in place. This migration:

* adds ``content_sha256``/``observed_at``/``provenance`` to ``market_candle`` and
  marks every pre-existing live row honestly: ``fixture`` when its ingestion
  source is the development fixture generator, otherwise ``legacy_unknown``.
  No hash or observation timestamp is fabricated for legacy rows. Governed rows
  keep NULL provenance because the dataset registration owns their provenance;
* creates the append-only ``market_candleobservation`` ledger;
* versions ``market_technicalsnapshot`` by algorithm and exact source candle set.
  Existing rows receive ``algorithm_version='technicals-v1'`` (deterministic:
  market/technicals.py has never changed) and ``legacy_unknown`` provenance;
* installs PostgreSQL triggers so live candles, observations and technical
  snapshots reject UPDATE/DELETE/TRUNCATE regardless of the ORM path. Only rows
  with ``fixture`` provenance may be deleted (development fixture replacement).

The governed-candle trigger function installed by earlier gates is not touched:
later migrations pin its body hash.
"""

import django.db.models.deletion
from django.db import migrations, models

LEGACY_LIVE_PROVENANCE_SQL = r"""
UPDATE market_candle AS candle
   SET provenance = CASE
         WHEN source.name = 'Development fixtures' THEN 'fixture'
         ELSE 'legacy_unknown'
       END
  FROM market_ingestionrun AS run
  JOIN market_sourceregistry AS source ON source.id = run.source_id
 WHERE run.id = candle.ingestion_run_id
   AND candle.dataset_version_id IS NULL
   AND candle.provenance IS NULL;
"""

CREATE_PROTECTION_SQL = r"""
CREATE FUNCTION market_live_candle_protect() RETURNS trigger AS $$
BEGIN
    IF OLD.dataset_version_id IS NOT NULL THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.provenance = 'fixture' THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'live candles are append-only; only fixture rows may be deleted';
    END IF;
    RAISE EXCEPTION 'live candles are append-only; record a revision observation instead';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER market_live_candle_protect
BEFORE UPDATE OR DELETE ON market_candle
FOR EACH ROW EXECUTE FUNCTION market_live_candle_protect();

CREATE FUNCTION market_technicalsnapshot_protect() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.provenance = 'fixture' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'technical snapshots are append-only; append a new calculation instead';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER market_technicalsnapshot_protect
BEFORE UPDATE OR DELETE ON market_technicalsnapshot
FOR EACH ROW EXECUTE FUNCTION market_technicalsnapshot_protect();

CREATE FUNCTION market_candleobservation_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'market_candleobservation is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER market_candleobservation_append_only
BEFORE UPDATE OR DELETE ON market_candleobservation
FOR EACH ROW EXECUTE FUNCTION market_candleobservation_reject_mutation();

CREATE FUNCTION market_live_evidence_reject_truncate() RETURNS trigger AS $$
BEGIN
    -- Django's test-database flush is the only permitted truncation (same
    -- escape hatch as market_discovery_reject_truncate).
    IF current_database() LIKE 'test\_%%' ESCAPE '\'
       AND EXISTS(
         SELECT 1 FROM pg_locks locks
         WHERE locks.pid=pg_backend_pid() AND locks.granted
           AND locks.mode='AccessExclusiveLock'
           AND locks.relation='auth_permission'::regclass
       ) THEN RETURN NULL; END IF;
    RAISE EXCEPTION '%% must not be truncated', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER market_candleobservation_reject_truncate
BEFORE TRUNCATE ON market_candleobservation
FOR EACH STATEMENT EXECUTE FUNCTION market_live_evidence_reject_truncate();
CREATE TRIGGER market_technicalsnapshot_reject_truncate
BEFORE TRUNCATE ON market_technicalsnapshot
FOR EACH STATEMENT EXECUTE FUNCTION market_live_evidence_reject_truncate();
"""

DROP_PROTECTION_SQL = r"""
DROP TRIGGER IF EXISTS market_technicalsnapshot_reject_truncate ON market_technicalsnapshot;
DROP TRIGGER IF EXISTS market_candleobservation_reject_truncate ON market_candleobservation;
DROP FUNCTION IF EXISTS market_live_evidence_reject_truncate();
DROP TRIGGER IF EXISTS market_candleobservation_append_only ON market_candleobservation;
DROP FUNCTION IF EXISTS market_candleobservation_reject_mutation();
DROP TRIGGER IF EXISTS market_technicalsnapshot_protect ON market_technicalsnapshot;
DROP FUNCTION IF EXISTS market_technicalsnapshot_protect();
DROP TRIGGER IF EXISTS market_live_candle_protect ON market_candle;
DROP FUNCTION IF EXISTS market_live_candle_protect();
"""


def mark_legacy_live_provenance(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(LEGACY_LIVE_PROVENANCE_SQL)


def create_protection(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE_PROTECTION_SQL)


def drop_protection(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP_PROTECTION_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0027_gate8i_final_dataset_acceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="candle",
            name="content_sha256",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="candle",
            name="observed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="candle",
            name="provenance",
            field=models.CharField(
                blank=True,
                choices=[
                    ("observed", "Observed live candle"),
                    ("fixture", "Development fixture"),
                    ("legacy_unknown", "Legacy row; provenance not recorded"),
                ],
                max_length=16,
                null=True,
            ),
        ),
        migrations.RunPython(mark_legacy_live_provenance, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="candle",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("dataset_version__isnull", False), ("provenance__isnull", True)),
                    models.Q(("dataset_version__isnull", True), ("provenance__isnull", False)),
                    _connector="OR",
                ),
                name="candle_provenance_matches_ownership",
            ),
        ),
        migrations.AddConstraint(
            model_name="candle",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("provenance", "observed"), _negated=True),
                    models.Q(("content_sha256__isnull", False), ("observed_at__isnull", False)),
                    _connector="OR",
                ),
                name="candle_observed_rows_carry_identity",
            ),
        ),
        migrations.AlterModelOptions(
            name="technicalsnapshot",
            options={"ordering": ("-as_of", "-calculated_at", "-id")},
        ),
        migrations.AddField(
            model_name="technicalsnapshot",
            name="algorithm_version",
            field=models.CharField(default="technicals-v1", max_length=40),
        ),
        migrations.AddField(
            model_name="technicalsnapshot",
            name="provenance",
            field=models.CharField(
                choices=[
                    ("observed", "Calculated from observed candles"),
                    ("fixture", "Calculated from development fixtures"),
                    ("legacy_unknown", "Legacy row; source binding not recorded"),
                ],
                default="legacy_unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="technicalsnapshot",
            name="source_candle_set_sha256",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="technicalsnapshot",
            name="unique_technical_snapshot",
        ),
        migrations.AddConstraint(
            model_name="technicalsnapshot",
            constraint=models.UniqueConstraint(
                fields=(
                    "instrument",
                    "granularity",
                    "as_of",
                    "algorithm_version",
                    "source_candle_set_sha256",
                ),
                name="unique_technical_snapshot_calculation",
            ),
        ),
        migrations.AddConstraint(
            model_name="technicalsnapshot",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("provenance", "legacy_unknown"),
                        ("source_candle_set_sha256__isnull", True),
                    ),
                    models.Q(
                        ("provenance__in", ("observed", "fixture")),
                        ("source_candle_set_sha256__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="technical_snapshot_binding_matches_provenance",
            ),
        ),
        migrations.CreateModel(
            name="CandleObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("W", "Weekly"),
                            ("D", "Daily"),
                            ("H4", "Four-hour"),
                            ("H1", "Hourly"),
                        ],
                        max_length=3,
                    ),
                ),
                ("timestamp", models.DateTimeField(help_text="UTC interval-start timestamp")),
                (
                    "interval_end",
                    models.DateTimeField(help_text="UTC interval completion under live semantics"),
                ),
                ("complete", models.BooleanField()),
                ("volume", models.PositiveIntegerField()),
                ("bid_open", models.DecimalField(decimal_places=6, max_digits=12)),
                ("bid_high", models.DecimalField(decimal_places=6, max_digits=12)),
                ("bid_low", models.DecimalField(decimal_places=6, max_digits=12)),
                ("bid_close", models.DecimalField(decimal_places=6, max_digits=12)),
                ("ask_open", models.DecimalField(decimal_places=6, max_digits=12)),
                ("ask_high", models.DecimalField(decimal_places=6, max_digits=12)),
                ("ask_low", models.DecimalField(decimal_places=6, max_digits=12)),
                ("ask_close", models.DecimalField(decimal_places=6, max_digits=12)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("initial", "First observation"),
                            (
                                "late_arrival",
                                "First observation arriving after later candles",
                            ),
                            ("revision", "Provider revision of an unreferenced candle"),
                            (
                                "conflict",
                                "Provider revision of a candle bound to frozen evidence",
                            ),
                        ],
                        max_length=16,
                    ),
                ),
                ("revision", models.PositiveIntegerField()),
                ("content_sha256", models.CharField(max_length=64)),
                ("differing_fields", models.JSONField(default=list)),
                ("observed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "candle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="observations",
                        to="market.candle",
                    ),
                ),
                (
                    "ingestion_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="candle_observations",
                        to="market.ingestionrun",
                    ),
                ),
                (
                    "instrument",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="market.instrument"
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="market.sourceregistry"
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="superseded_by",
                        to="market.candleobservation",
                    ),
                ),
            ],
            options={
                "ordering": ("instrument", "granularity", "timestamp", "revision"),
                "indexes": [
                    models.Index(fields=["candle", "-revision"], name="candle_observation_rev_idx")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "instrument",
                            "granularity",
                            "timestamp",
                            "source",
                            "content_sha256",
                        ),
                        name="unique_candle_observation_content",
                    ),
                    models.UniqueConstraint(
                        fields=("instrument", "granularity", "timestamp", "source", "revision"),
                        name="unique_candle_observation_revision",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("complete", True)), name="candle_observation_complete"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("kind__in", ("initial", "late_arrival")),
                                ("revision", 1),
                                ("supersedes__isnull", True),
                            ),
                            models.Q(("kind__in", ("revision", "conflict")), ("revision__gt", 1)),
                            _connector="OR",
                        ),
                        name="candle_observation_revision_shape",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("timestamp__lt", models.F("interval_end"))),
                        name="candle_observation_increasing_interval",
                    ),
                ],
            },
        ),
        migrations.RunPython(create_protection, drop_protection),
    ]
