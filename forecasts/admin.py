from django.contrib import admin

from forecasts.models import (
    EvidenceSnapshot,
    Forecast,
    ForecastResolution,
    PaperTradeEntry,
    PaperTradeResult,
    PositionSizeAdvice,
    Recommendation,
    RecommendationResolution,
    TargetContract,
)

admin.site.register(TargetContract)
admin.site.register(EvidenceSnapshot)
admin.site.register(Forecast)
admin.site.register(ForecastResolution)
admin.site.register(PaperTradeEntry)
admin.site.register(PaperTradeResult)
admin.site.register(PositionSizeAdvice)
admin.site.register(Recommendation)
admin.site.register(RecommendationResolution)
