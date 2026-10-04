import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from application import audiobook
from application.audiobook import SynthesisSettings, _synthesize_text_to_wav, create_audiobook
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
    def test_document_section_audio_is_streamed_to_a_temporary_wav(self):
        backend = FakeBackend()
        sample_rate, target = _synthesize_text_to_wav(
            backend,
            backend.synthesize,
            "One. Two. Three.",
            None,
            SynthesisSettings(max_chunk_chars=8, pause_ms=100),
            lambda _value, _message: None,
            0.0,
            1.0,
        )
        try:
            samples, written_rate = sf.read(target, dtype="float32")
            self.assertEqual(sample_rate, written_rate)
            self.assertEqual(
                len(samples),
                len(backend.requests) * 2 + max(0, len(backend.requests) - 1),
            )
        finally:
            target.unlink(missing_ok=True)

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

    def test_document_wavs_are_deleted_after_assembly(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "section.wav"

            def save_section_audio(_document_id, _section_id, temporary, _sample_rate):
                Path(temporary).replace(generated)
                return generated

            with (
                patch.object(audiobook, "prepare_entire_document", return_value=["section"]),
                patch.object(audiobook, "load_section", return_value={"text": "One. Two."}),
                patch.object(audiobook, "save_document_audio", side_effect=save_section_audio),
                patch.object(audiobook, "create_batch_item", return_value={}),
                patch.object(audiobook, "assemble_chapters", return_value=Path(directory) / "book.m4b"),
                patch.object(audiobook, "clear_document_audio_paths"),
            ):
                create_audiobook(
                    backend=backend,
                    document_path=None,
                    pasted_text=None,
                    reference_audio=None,
                    settings=SynthesisSettings(max_chunk_chars=8),
                    ffmpeg_path="ffmpeg",
                    ffprobe_path="ffprobe",
                    output_directory=directory,
                    document_id="test_document",
                )
            self.assertFalse(generated.exists())


if __name__ == "__main__":
    unittest.main()
