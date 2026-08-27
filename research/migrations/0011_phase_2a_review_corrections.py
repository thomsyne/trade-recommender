import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

TABLES = (
    "research_strategydefinition",
    "research_strategyversion",
    "research_strategyparametermanifest",
    "research_level",
    "research_levellifecycleevent",
    "research_levelproximityevent",
    "research_analysisrun",
    "research_setupevent",
    "research_setuplevelattribution",
    "research_setuptransition",
    "research_entryeligibilityevaluation",
    "research_jobrun",
)


def preflight_registered_identities(apps, schema_editor):
    AnalysisRun = apps.get_model("research", "AnalysisRun")
    SetupTransition = apps.get_model("research", "SetupTransition")
    EntryEligibilityEvaluation = apps.get_model("research", "EntryEligibilityEvaluation")

    analyses = {}
    for analysis in AnalysisRun.objects.select_related("strategy_version").order_by("pk"):
        key = (
            analysis.instrument_id,
            analysis.completed_h1_timestamp,
            analysis.strategy_version.detector_version,
            analysis.dataset_version_id,
        )
        retained = analyses.get(key)
        if retained and (retained.result, retained.evidence_hash) != (
            analysis.result,
            analysis.evidence_hash,
        ):
            raise RuntimeError("AnalysisRun rows conflict under detector-version identity")
        analyses.setdefault(key, analysis)

    if EntryEligibilityEvaluation.objects.filter(decision="ENTRY_PENDING").exists():
        raise RuntimeError(
            "existing ENTRY_PENDING evaluations lack registered CAD conversion evidence; "
            "prove the Phase 2A tables empty or migrate that evidence explicitly"
        )

    transitions_by_setup = {}
    for transition in SetupTransition.objects.filter(from_state="CONFIRMED").order_by("pk"):
        transitions_by_setup.setdefault(transition.setup_id, []).append(transition)
    setup_ids = set(transitions_by_setup) | set(
        EntryEligibilityEvaluation.objects.values_list("setup_id", flat=True)
    )
    for setup_id in setup_ids:
        sources = {}
        for transition in transitions_by_setup.get(setup_id, []):
            retained = sources.get(transition.to_state)
            if retained and (
                retained.effective_at,
                retained.evidence,
                retained.evidence_hash,
                retained.reason,
                retained.job_run_id,
            ) != (
                transition.effective_at,
                transition.evidence,
                transition.evidence_hash,
                transition.reason,
                transition.job_run_id,
            ):
                raise RuntimeError("existing entry transition evidence is ambiguous")
            sources.setdefault(transition.to_state, transition)
        decisions = set(
            EntryEligibilityEvaluation.objects.filter(setup_id=setup_id).values_list(
                "decision", flat=True
            )
        )
        if set(sources) != decisions:
            raise RuntimeError("existing entry transitions do not match eligibility evaluations")


def drop_append_only_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {table}_reject_mutation();")
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS research_setup_attribution_validate ON "
        "research_setuplevelattribution;"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS research_validate_setup_attribution();")


def restore_original_append_only_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        function = f"{table}_reject_mutation"
        trigger = f"{table}_append_only"
        schema_editor.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{table} is append-only';
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}();
            """
        )


def restore_corrected_triggers(apps, schema_editor):
    restore_original_append_only_triggers(apps, schema_editor)
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE FUNCTION research_validate_setup_attribution() RETURNS trigger AS $$
        DECLARE
            frozen_keys jsonb;
            setup_instrument bigint;
            setup_strategy bigint;
            setup_dataset bigint;
            setup_direction text;
            level_key text;
            level_instrument bigint;
            level_strategy bigint;
            level_dataset bigint;
            level_role text;
        BEGIN
            SELECT attribution_keys, instrument_id, strategy_version_id,
                   dataset_version_id, direction
              INTO frozen_keys, setup_instrument, setup_strategy, setup_dataset, setup_direction
              FROM research_setupevent WHERE id = NEW.setup_id;
            SELECT stable_key, instrument_id, strategy_version_id, dataset_version_id, role
              INTO level_key, level_instrument, level_strategy, level_dataset, level_role
              FROM research_level WHERE id = NEW.level_id;
            IF NOT (frozen_keys ? level_key)
               OR setup_instrument <> level_instrument
               OR setup_strategy <> level_strategy
               OR setup_dataset <> level_dataset
               OR (setup_direction = 'long' AND level_role <> 'support')
               OR (setup_direction = 'short' AND level_role <> 'resistance') THEN
                RAISE EXCEPTION 'setup attribution conflicts with frozen setup lineage';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER research_setup_attribution_validate
        BEFORE INSERT ON research_setuplevelattribution
        FOR EACH ROW EXECUTE FUNCTION research_validate_setup_attribution();
        """
    )


def populate_registered_identities(apps, schema_editor):
    AnalysisRun = apps.get_model("research", "AnalysisRun")
    SetupTransition = apps.get_model("research", "SetupTransition")
    EntryEligibilityEvaluation = apps.get_model("research", "EntryEligibilityEvaluation")
    SetupLevelAttribution = apps.get_model("research", "SetupLevelAttribution")

    retained_analyses = {}
    for analysis in AnalysisRun.objects.select_related("strategy_version").order_by("pk"):
        analysis.detector_version = analysis.strategy_version.detector_version
        key = (
            analysis.instrument_id,
            analysis.completed_h1_timestamp,
            analysis.detector_version,
            analysis.dataset_version_id,
        )
        retained = retained_analyses.get(key)
        if retained:
            if (retained.result, retained.evidence_hash) != (
                analysis.result,
                analysis.evidence_hash,
            ):
                raise RuntimeError(
                    "existing AnalysisRun rows conflict under detector-version identity"
                )
            analysis.delete()
        else:
            analysis.save(update_fields=("detector_version",))
            retained_analyses[key] = analysis

    entry_transitions = {}
    for transition in SetupTransition.objects.select_related("setup__strategy_version").order_by(
        "pk"
    ):
        setup = transition.setup
        if transition.from_state == "CONFIRMED":
            entry_transitions.setdefault(setup.pk, []).append(transition)
            continue
        transition.strategy_version_id = setup.strategy_version_id
        transition.dataset_version_id = setup.dataset_version_id
        transition.execution_identity = setup.strategy_version.execution_identity
        transition.decision_at = transition.effective_at
        transition.save(
            update_fields=(
                "strategy_version",
                "dataset_version",
                "execution_identity",
                "decision_at",
                "book_identity",
            )
        )

    setup_ids = set(entry_transitions) | set(
        EntryEligibilityEvaluation.objects.values_list("setup_id", flat=True)
    )
    for setup_id in sorted(setup_ids):
        transitions = entry_transitions.get(setup_id, [])
        evaluations = list(
            EntryEligibilityEvaluation.objects.filter(setup_id=setup_id).order_by(
                "book_identity", "pk"
            )
        )
        sources_by_decision = {}
        for transition in transitions:
            retained = sources_by_decision.get(transition.to_state)
            if retained and (
                retained.effective_at,
                retained.evidence,
                retained.evidence_hash,
                retained.reason,
                retained.job_run_id,
            ) != (
                transition.effective_at,
                transition.evidence,
                transition.evidence_hash,
                transition.reason,
                transition.job_run_id,
            ):
                raise RuntimeError("existing entry transition evidence is ambiguous")
            sources_by_decision.setdefault(transition.to_state, transition)
        if set(sources_by_decision) != {evaluation.decision for evaluation in evaluations}:
            raise RuntimeError("existing entry transitions do not match eligibility evaluations")

        SetupTransition.objects.filter(setup_id=setup_id, from_state="CONFIRMED").delete()
        for evaluation in evaluations:
            source = sources_by_decision[evaluation.decision]
            setup = source.setup
            SetupTransition.objects.create(
                setup_id=setup_id,
                book_identity=evaluation.book_identity,
                from_state="CONFIRMED",
                to_state=source.to_state,
                effective_at=source.effective_at,
                decision_at=source.effective_at,
                evidence=source.evidence,
                evidence_hash=source.evidence_hash,
                reason=source.reason,
                strategy_version_id=setup.strategy_version_id,
                dataset_version_id=setup.dataset_version_id,
                execution_identity=setup.strategy_version.execution_identity,
                job_run_id=source.job_run_id,
            )

    for setup in apps.get_model("research", "SetupEvent").objects.all():
        setup.attribution_keys = sorted(
            SetupLevelAttribution.objects.filter(setup_id=setup.pk).values_list(
                "level__stable_key", flat=True
            )
        )
        setup.save(update_fields=("attribution_keys",))

    seen = set()
    for transition in SetupTransition.objects.order_by("pk"):
        key = (transition.setup_id, transition.from_state, transition.book_identity)
        if key in seen:
            raise RuntimeError("existing setup transition ledger contains a fork")
        seen.add(key)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("market", "0008_reject_governed_candle_promotion"),
        ("research", "0010_phase_2a_append_only_triggers"),
    ]
    operations = [
        migrations.RunPython(
            preflight_registered_identities,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.RunPython(drop_append_only_triggers, restore_original_append_only_triggers),
        migrations.RemoveConstraint(
            model_name="analysisrun",
            name="unique_analysis_instrument_h1_strategy_dataset",
        ),
        migrations.RemoveConstraint(
            model_name="setuptransition",
            name="unique_setup_transition",
        ),
        migrations.RemoveConstraint(
            model_name="setuptransition",
            name="valid_phase2a_setup_transition",
        ),
        migrations.RemoveConstraint(
            model_name="entryeligibilityevaluation",
            name="eligibility_fields_match_decision",
        ),
        migrations.AddField(
            model_name="analysisrun",
            name="detector_version",
            field=models.CharField(max_length=80, null=True),
        ),
        migrations.AddField(
            model_name="setupevent",
            name="attribution_keys",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="setuptransition",
            name="book_identity",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="setuptransition",
            name="decision_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="setuptransition",
            name="dataset_version",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="market.datasetversion",
            ),
        ),
        migrations.AddField(
            model_name="setuptransition",
            name="execution_identity",
            field=models.CharField(blank=True, default="", max_length=160),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="setuptransition",
            name="strategy_version",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="research.strategyversion",
            ),
        ),
        migrations.AddField(
            model_name="entryeligibilityevaluation",
            name="conversion_effective_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="entryeligibilityevaluation",
            name="conversion_identity",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="entryeligibilityevaluation",
            name="conversion_rate_to_cad",
            field=models.DecimalField(blank=True, decimal_places=10, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name="entryeligibilityevaluation",
            name="risk_per_unit_cad",
            field=models.DecimalField(blank=True, decimal_places=10, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name="entryeligibilityevaluation",
            name="risk_per_unit_quote",
            field=models.DecimalField(blank=True, decimal_places=10, max_digits=20, null=True),
        ),
        migrations.RunPython(
            populate_registered_identities,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AlterField(
            model_name="analysisrun",
            name="detector_version",
            field=models.CharField(max_length=80),
        ),
        migrations.AlterField(
            model_name="setuptransition",
            name="decision_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="setuptransition",
            name="dataset_version",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="market.datasetversion",
            ),
        ),
        migrations.AlterField(
            model_name="setuptransition",
            name="execution_identity",
            field=models.CharField(max_length=160),
        ),
        migrations.AlterField(
            model_name="setuptransition",
            name="strategy_version",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="research.strategyversion",
            ),
        ),
        migrations.AddConstraint(
            model_name="analysisrun",
            constraint=models.UniqueConstraint(
                fields=(
                    "instrument",
                    "completed_h1_timestamp",
                    "detector_version",
                    "dataset_version",
                ),
                name="unique_analysis_instrument_h1_detector_dataset",
            ),
        ),
        migrations.AddConstraint(
            model_name="setuptransition",
            constraint=models.UniqueConstraint(
                fields=("setup", "from_state", "book_identity"),
                name="unique_setup_outgoing_transition",
            ),
        ),
        migrations.AddConstraint(
            model_name="setuptransition",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        from_state="TRIGGER_PENDING",
                        book_identity="",
                        to_state__in=(
                            "CONFIRMED",
                            "INVALIDATED",
                            "EXPIRED",
                            "CANCELLED_DATA_QUALITY",
                        ),
                    )
                    | models.Q(
                        from_state="CONFIRMED",
                        book_identity__gt="",
                        to_state__in=(
                            "ENTRY_PENDING",
                            "MISSED_FILL",
                            "BLOCKED_SESSION",
                            "BLOCKED_SPREAD",
                            "NO_TARGET",
                            "INSUFFICIENT_REWARD",
                            "CANCELLED_DATA_QUALITY",
                        ),
                    )
                ),
                name="valid_phase2a_setup_transition",
            ),
        ),
        migrations.AddConstraint(
            model_name="entryeligibilityevaluation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        decision="ENTRY_PENDING",
                        terminal_reason="",
                        entry_timestamp__isnull=False,
                        entry_price__isnull=False,
                        stop_price__isnull=False,
                        target_price__isnull=False,
                        reward_risk__isnull=False,
                        risk_per_unit_quote__isnull=False,
                        conversion_rate_to_cad__isnull=False,
                        conversion_effective_at__isnull=False,
                        conversion_identity__gt="",
                        risk_per_unit_cad__isnull=False,
                        target_level__isnull=False,
                    )
                    | models.Q(
                        decision__in=(
                            "MISSED_FILL",
                            "BLOCKED_SESSION",
                            "BLOCKED_SPREAD",
                            "NO_TARGET",
                            "INSUFFICIENT_REWARD",
                            "CANCELLED_DATA_QUALITY",
                        ),
                        terminal_reason__gt="",
                        entry_timestamp__isnull=True,
                        entry_price__isnull=True,
                        stop_price__isnull=True,
                        target_price__isnull=True,
                        reward_risk__isnull=True,
                        risk_per_unit_quote__isnull=True,
                        conversion_rate_to_cad__isnull=True,
                        conversion_effective_at__isnull=True,
                        conversion_identity="",
                        risk_per_unit_cad__isnull=True,
                        target_level__isnull=True,
                    )
                ),
                name="eligibility_fields_match_decision",
            ),
        ),
        migrations.RunPython(restore_corrected_triggers, drop_append_only_triggers),
    ]
