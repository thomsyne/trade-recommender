"""Phase7 registration must not change the historical S1 model source pin."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class Phase7RegistrationTests(SimpleTestCase):
    def test_historical_models_keep_exact_base_bytes(self):
        self.assertEqual(
            hashlib.sha256((ROOT / "research/models.py").read_bytes()).hexdigest(),
            "cb72ee3f0ea35b6e0388bdc26394c80c283607d20c7be0a473c77d6ffe5048e9",
        )

    def test_all_evidence_models_exist_before_ready_with_original_migration_ownership(self):
        # A fresh interpreter catches registration deferred until ready(), cached
        # test imports masking missing registration, and accidental app/table moves.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
import django
from research.apps import ResearchConfig

expected = (
    'EvidenceRightsReview', 'ExactEvidence', 'EvidenceConflict',
    'FrozenEvidencePacket', 'EvidenceIncident', 'EvidenceContextResult',
    'EvidenceLegacyAdmission',
)
original_ready = ResearchConfig.ready
def check_ready(self):
    assert self.apps.models_ready
    assert 'research.evidence_models' in sys.modules
    assert self.models_module.__name__ == 'research.models'
    extension = sys.modules['research.evidence_models']
    for name in expected:
        model = self.get_model(name)
        assert model is getattr(extension, name)
        assert model._meta.app_label == 'research'
        assert model._meta.db_table == 'research_' + name.lower()
        assert not hasattr(self.models_module, name)
    original_ready(self)
ResearchConfig.ready = check_ready
django.setup()

from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ModelState
state = MigrationLoader(None).project_state()
for name in expected:
    model = django.apps.apps.get_model('research', name)
    assert ModelState.from_model(model) == state.models['research', name.lower()]
print('phase-two registration and migration state match')
""",
            ],
            cwd=ROOT,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("phase-two registration and migration state match", result.stdout)
