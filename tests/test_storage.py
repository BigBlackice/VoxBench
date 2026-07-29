import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import gradio as gr
import numpy as np
import soundfile as sf

from webui.storage import (
    generated_audio_filename,
    list_reference_samples,
    route_uploaded_file,
    sanitize_sample_filename,
    save_generated_audio,
    save_reference_sample,
)


class ReferenceSampleStorageTests(unittest.TestCase):
    def test_sanitizes_portable_filename(self):
        self.assertEqual(sanitize_sample_filename("My voice: take 1.WAV"), "My_voice_take_1.wav")
        self.assertEqual(sanitize_sample_filename("CON.wav"), "CON_sample.wav")

    def test_saves_without_overwriting_name_collision(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_source = root / "first" / "Voice clip.wav"
            second_source = root / "second" / "Voice clip.wav"
            samples_dir = root / "samples"
            first_source.parent.mkdir()
            second_source.parent.mkdir()
            first_source.write_bytes(b"first recording")
            second_source.write_bytes(b"second recording")

            first_saved = save_reference_sample(str(first_source), samples_dir)
            duplicate_saved = save_reference_sample(str(first_source), samples_dir)
            second_saved = save_reference_sample(str(second_source), samples_dir)

            self.assertEqual(first_saved, duplicate_saved)
            self.assertEqual(first_saved.name, "Voice_clip.wav")
            self.assertEqual(second_saved.name, "Voice_clip_2.wav")
            self.assertEqual(len(list_reference_samples(samples_dir)), 2)

    def test_generated_filename_is_readable(self):
        filename = generated_audio_filename(
            "Hello there! [chuckle] This is a test.",
            datetime(2026, 7, 24, 12, 34, 56),
        )

        self.assertEqual(filename, "20260724_123456_Hello_there_This_is_a.wav")

    def test_saves_generated_wav_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            audio = np.zeros(240, dtype=np.float32)

            first_saved = save_generated_audio(
                audio,
                sample_rate=24000,
                text="Test output",
                directory=temporary_directory,
            )
            second_saved = save_generated_audio(
                audio,
                sample_rate=24000,
                text="Test output",
                directory=temporary_directory,
            )

            first_audio, first_rate = sf.read(first_saved)
            self.assertTrue(first_saved.is_file())
            self.assertTrue(second_saved.is_file())
            self.assertNotEqual(first_saved, second_saved)
            self.assertEqual(first_rate, 24000)
            self.assertEqual(len(first_audio), 240)

    def test_routes_text_and_audio_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            text_file = root / "prompt.txt"
            audio_file = root / "voice.wav"
            samples_dir = root / "samples"
            text_file.write_text("Text from a file.", encoding="utf-8")
            audio_file.write_bytes(b"reference audio")

            text_kind, text_value = route_uploaded_file(str(text_file), samples_dir)
            audio_kind, audio_value = route_uploaded_file(str(audio_file), samples_dir)

            self.assertEqual((text_kind, text_value), ("text", "Text from a file."))
            self.assertEqual(audio_kind, "audio")
            self.assertEqual(audio_value.parent, samples_dir.resolve())
            self.assertTrue(audio_value.is_file())

    def test_rejects_unsupported_shared_upload(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            unsupported = Path(temporary_directory) / "archive.zip"
            unsupported.write_bytes(b"not supported")

            with self.assertRaises(gr.Error):
                route_uploaded_file(str(unsupported), Path(temporary_directory) / "samples")


if __name__ == "__main__":
    unittest.main()
