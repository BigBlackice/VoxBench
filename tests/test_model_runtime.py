import unittest
from pathlib import Path

from model_service.runtime import ChatterboxRuntime


class ModelRuntimeTests(unittest.TestCase):
    def test_reference_session_uses_disk_and_is_removed_on_close(self):
        runtime = ChatterboxRuntime()
        try:
            token = runtime.create_reference_session("voice.wav", b"reference audio")
            path = Path(runtime.reference_for_session(token))
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"reference audio")

            runtime.close_reference_session(token)
            self.assertFalse(path.exists())
            self.assertIsNone(runtime.reference_for_session(token))
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
