import json
import tempfile
import unittest
from pathlib import Path

from webui.app_config import (
    SECRET_FIELD_MASK,
    ModelConnectionSettings,
    load_model_connection,
    masked_secret,
    save_model_connection,
    updated_secret,
)
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

    def test_secret_field_mask_never_contains_the_saved_secret(self):
        self.assertEqual(masked_secret("secret-value"), SECRET_FIELD_MASK)
        self.assertEqual(updated_secret("", "secret-value"), "secret-value")
        self.assertEqual(updated_secret("replacement", "secret-value"), "replacement")


if __name__ == "__main__":
    unittest.main()
