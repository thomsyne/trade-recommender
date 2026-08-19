from django.contrib import admin

from research.models import (
    DocumentRepresentation,
    MacroObservation,
    MacroSeries,
    ProviderEvaluation,
    RawRetrieval,
    ResearchDiscrepancy,
    ResearchDocument,
    SourcePolicy,
)

admin.site.register(SourcePolicy)
admin.site.register(RawRetrieval)
admin.site.register(ResearchDocument)
admin.site.register(DocumentRepresentation)
admin.site.register(MacroSeries)
admin.site.register(MacroObservation)
admin.site.register(ResearchDiscrepancy)
admin.site.register(ProviderEvaluation)
