from django.contrib import admin

from forecasts.models import (
    EvidenceSnapshot,
    Forecast,
    ForecastResolution,
    Recommendation,
    TargetContract,
)

admin.site.register(TargetContract)
admin.site.register(EvidenceSnapshot)
admin.site.register(Forecast)
admin.site.register(ForecastResolution)
admin.site.register(Recommendation)
