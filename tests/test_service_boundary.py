import ast
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


class ServiceBoundaryTests(unittest.TestCase):
    def test_application_code_does_not_import_model_packages(self):
        application_files = [PROJECT_DIR / "app.py"]
        application_files.extend((PROJECT_DIR / "inference").glob("*.py"))
        application_files.extend((PROJECT_DIR / "webui").glob("*.py"))
        violations = {
            str(path.relative_to(PROJECT_DIR)): imported_roots(path)
            & {"torch", "chatterbox"}
            for path in application_files
            if imported_roots(path) & {"torch", "chatterbox"}
        }
        self.assertEqual(violations, {})

    def test_model_service_does_not_import_application_workflows(self):
        forbidden = {
            "chapter_assembly",
            "document_workspace",
            "storage",
            "audio_processing",
        }
        service_files = [PROJECT_DIR / "model_server.py"]
        service_files.extend((PROJECT_DIR / "model_service").glob("*.py"))
        for path in service_files:
            source = path.read_text(encoding="utf-8")
            self.assertFalse(
                any(name in source for name in forbidden),
                f"Application workflow imported by {path.name}",
            )


if __name__ == "__main__":
    unittest.main()
