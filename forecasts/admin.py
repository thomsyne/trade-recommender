from django.contrib import admin

from forecasts.models import (
    EvidenceSnapshot,
    Forecast,
    ForecastResolution,
    Recommendation,
    RecommendationResolution,
    TargetContract,
)

admin.site.register(TargetContract)
admin.site.register(EvidenceSnapshot)
admin.site.register(Forecast)
admin.site.register(ForecastResolution)
admin.site.register(Recommendation)
admin.site.register(RecommendationResolution)
