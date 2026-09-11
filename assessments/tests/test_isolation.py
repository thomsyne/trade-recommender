import ast
import hashlib
import json
from pathlib import Path
from unittest import TestCase

from assessments.source_pins import PINS, verify


class IsolationTests(TestCase):
    def test_active_stack_source_pins_are_unchanged(self):
        verify()

    def test_candidate_source_manifest_is_exact(self):
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / "docs/phase6a/source-manifest.json").read_text())
        self.assertEqual(manifest["base_commit"], "005b21f042cbc0aacd556c83ef16c86742cba06a")
        for relative, expected in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((root / relative).read_bytes()).hexdigest(), expected)

    def test_bilateral_import_boundary(self):
        root = Path(__file__).resolve().parents[2]
        active = tuple(PINS)
        for relative in active:
            imports = {
                (node.module or "").split(".")[0]
                for node in ast.walk(ast.parse((root / relative).read_text()))
                if isinstance(node, ast.ImportFrom)
            }
            self.assertNotIn("assessments", imports)
        forbidden = {"forecasts", "operations", "anthropic", "oanda"}
        for path in (root / "assessments").glob("*.py"):
            imports = {
                node.names[0].name.split(".")[0]
                if isinstance(node, ast.Import)
                else (node.module or "").split(".")[0]
                for node in ast.walk(ast.parse(path.read_text()))
                if isinstance(node, (ast.Import, ast.ImportFrom))
            }
            self.assertFalse(imports & forbidden, f"forbidden import in {path.name}")

    def test_no_schedule_task_provider_or_model_surface(self):
        root = Path(__file__).resolve().parents[1]
        names = {path.name for path in root.rglob("*.py")}
        self.assertFalse(names & {"tasks.py", "schedules.py", "admin.py"})
