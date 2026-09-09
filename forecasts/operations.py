"""Budget-free durable Phase3 reconciliation; explicit era registration gates work."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from forecasts.models import ExperimentEra
from market.models import Instrument

TASK = "forecast.reconcile_target_lifecycle"


def enabled():
    return ExperimentEra.objects.filter(
        method__contract_version=4, starts_at__lte=timezone.now()
    ).exists()


def reconcile(parameters):
    if (
        not isinstance(parameters, dict)
        or set(parameters) != {"instrument"}
        or not isinstance(parameters["instrument"], str)
        or parameters["instrument"] not in {"EUR_USD", "GBP_USD", "EUR_GBP", "USD_CAD"}
    ):
        raise ValidationError("invalid_reconciliation_identity")
    instrument = Instrument.objects.get(code=parameters["instrument"], active=True)
    if not enabled():
        raise ValidationError("prospective_era_registration_required")
    from forecasts.experiments import refresh_all_experiments
    from forecasts.lifecycle import reconcile_lifecycle
    from forecasts.paper import resolve_due_paper_trades
    from forecasts.recommendations import resolve_due_recommendations
    from forecasts.services import resolve_due_forecasts
    from forecasts.targets import reconcile_targets

    errors = []
    result = None
    steps = (
        ("target_control", lambda: reconcile_targets(instrument)),
        ("forecast_resolution", lambda: resolve_due_forecasts(instrument)),
        ("recommendation_resolution", lambda: resolve_due_recommendations(instrument)),
        ("lifecycle", lambda: reconcile_lifecycle(instrument)),
        ("paper", lambda: resolve_due_paper_trades(instrument)),
        ("lifecycle_after_paper", lambda: reconcile_lifecycle(instrument)),
        ("experiment_health", refresh_all_experiments),
    )
    for code, operation in steps:
        try:
            value = operation()
            if code == "target_control":
                result = value
        except Exception:
            # Each owning service is atomic; repair independent state even if
            # market evidence/control recovery fails. No provider bodies escape.
            errors.append(code)
    if errors:
        raise ValidationError("phase3_reconciliation_failed:" + ",".join(errors))
    return result
