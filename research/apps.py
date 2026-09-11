from importlib import import_module

from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "research"

    def import_models(self):
        super().import_models()
        # Register during phase two, before models_ready or any app's ready().
        # The historical models module is source-pinned by S1 governance.
        import_module("research.evidence_models")
