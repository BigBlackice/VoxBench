import unittest
from pathlib import Path

from model_service.runtime import ChatterboxRuntime


class ModelRuntimeTests(unittest.TestCase):
    def test_reuses_prepared_conditionals_for_the_same_reference(self):
        class Model:
            conds = "default"

            def __init__(self):
                self.prepared = []

            def prepare_conditionals(self, path, norm_loudness):
                self.prepared.append((path, norm_loudness))
                self.conds = path

        runtime = ChatterboxRuntime()
        model = Model()
        runtime._default_conditionals = model.conds
        try:
            runtime._prepare_reference_conditionals(model, "voice.wav", True)
            runtime._prepare_reference_conditionals(model, "voice.wav", True)
            self.assertEqual(model.prepared, [("voice.wav", True)])

            runtime._prepare_reference_conditionals(model, None, True)
            self.assertEqual(model.conds, "default")
        finally:
            runtime.close()

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
