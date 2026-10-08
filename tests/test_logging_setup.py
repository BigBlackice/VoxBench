import tempfile
import unittest
from pathlib import Path

from app_logic.logging_setup import build_log_config


class LoggingSetupTests(unittest.TestCase):
    def test_creates_a_bounded_component_log_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_log_config(Path(directory), "app")

            handler = config["handlers"]["file"]
            self.assertEqual(handler["filename"], str(Path(directory) / "logs" / "app.log"))
            self.assertEqual(handler["maxBytes"], 5 * 1024 * 1024)
            self.assertEqual(handler["backupCount"], 3)
            self.assertTrue((Path(directory) / "logs").is_dir())


if __name__ == "__main__":
    unittest.main()
