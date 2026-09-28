import json
import tempfile
import unittest
from pathlib import Path

from webui.app_config import ModelConnectionSettings, load_model_connection, save_model_connection
from webui.errors import VoxBenchError


class AppConfigTests(unittest.TestCase):
    def test_missing_config_creates_local_model_service_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voxbench.json"
            settings = load_model_connection(path)

            self.assertEqual(settings.connection_type, "service")
            self.assertEqual(settings.service_url, "http://127.0.0.1:7861")
            self.assertEqual(json.loads(path.read_text())["model_connection"]["service_url"], settings.service_url)

    def test_connection_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voxbench.json"
            original = ModelConnectionSettings(
                service_url="https://tts.example.test",
                service_api_key="test-key",
                timeout_seconds=45,
            )
            save_model_connection(original, path)

            self.assertEqual(load_model_connection(path), original)

    def test_provider_requires_endpoint(self):
        with self.assertRaises(VoxBenchError):
            ModelConnectionSettings(connection_type="provider").validate()


if __name__ == "__main__":
    unittest.main()
