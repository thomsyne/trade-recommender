from importlib import import_module

from django.db import migrations


def _helpers():
    return import_module("research.migrations.0011_phase_2a_review_corrections")


def rewrite_with_protection(apps, schema_editor, *, inject_failure=False):
    helpers = _helpers()
    helpers.drop_append_only_triggers(apps, schema_editor)
    helpers.populate_registered_identities(apps, schema_editor)
    if inject_failure:
        raise RuntimeError("injected migration failure")
    helpers.restore_corrected_triggers(apps, schema_editor)


def reverse_rewrite_with_protection(apps, schema_editor):
    helpers = _helpers()
    helpers.drop_append_only_triggers(apps, schema_editor)
    AnalysisRun = apps.get_model("research", "AnalysisRun")
    SetupEvent = apps.get_model("research", "SetupEvent")
    SetupTransition = apps.get_model("research", "SetupTransition")

    for setup_id in (
        SetupTransition.objects.filter(from_state="CONFIRMED")
        .values_list("setup_id", flat=True)
        .distinct()
    ):
        transitions = list(
            SetupTransition.objects.filter(setup_id=setup_id, from_state="CONFIRMED").order_by("pk")
        )
        retained_by_state = {}
        for transition in transitions:
            retained = retained_by_state.get(transition.to_state)
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
                raise RuntimeError("book transitions cannot be reversed without data loss")
            if retained:
                transition.delete()
            else:
                retained_by_state[transition.to_state] = transition

    SetupTransition.objects.update(
        book_identity="",
        decision_at=None,
        dataset_version=None,
        execution_identity="",
        strategy_version=None,
    )
    AnalysisRun.objects.update(detector_version=None)
    SetupEvent.objects.update(attribution_keys=[])
    helpers.restore_original_append_only_triggers(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0011_phase_2a_review_corrections"),
    ]

    operations = [
        migrations.RunPython(
            rewrite_with_protection,
            reverse_rewrite_with_protection,
        )
    ]
