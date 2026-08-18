from django.contrib import admin

from market.models import (
    AuditEvent,
    Candle,
    IngestionRun,
    Instrument,
    SourceRegistry,
    TechnicalSnapshot,
)

admin.site.register(Instrument)
admin.site.register(SourceRegistry)
admin.site.register(IngestionRun)
admin.site.register(Candle)
admin.site.register(TechnicalSnapshot)
admin.site.register(AuditEvent)
