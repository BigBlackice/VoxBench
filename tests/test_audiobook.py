import tempfile
import unittest
from pathlib import Path

import numpy as np

from application.audiobook import SynthesisSettings, create_audiobook
from inference.contract import AudioResult


class FakeBackend:
    label = "Test backend"
    sample_rate = 10

    def __init__(self):
        self.requests = []

    def capabilities(self):
        return {}

    def synthesize(self, request):
        self.requests.append(request)
        return AudioResult(10, np.ones(2, dtype=np.float32))


class AudiobookTests(unittest.TestCase):
    def test_pasted_text_is_chunked_and_saved_by_the_application(self):
        backend = FakeBackend()
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            result = create_audiobook(
                backend=backend,
                document_path=None,
                pasted_text="One. Two. Three.",
                reference_audio=None,
                settings=SynthesisSettings(max_chunk_chars=8, pause_ms=100),
                ffmpeg_path=None,
                ffprobe_path=None,
                output_directory=directory,
                output_format=".wav",
                progress=lambda value, message: updates.append((value, message)),
            )
            self.assertTrue(result.output_path.is_file())
            self.assertEqual(result.output_path.parent, Path(directory))

        self.assertGreaterEqual(len(backend.requests), 2)
        self.assertEqual(result.document_id, None)
        self.assertEqual(result.section_count, 1)
        self.assertTrue(updates)


if __name__ == "__main__":
    unittest.main()
