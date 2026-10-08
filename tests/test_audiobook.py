import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from application import audiobook
from application.audiobook import SynthesisSettings, _synthesize_parts_to_wav, _synthesize_text_to_wav, create_audiobook
from app_logic.generation_control import GenerationController
from inference.contract import AudioResult
from webui.errors import VoxBenchError


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

    def test_long_pasted_text_streams_to_a_temporary_wav(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            temporary_wav = Path(directory) / "streamed.wav"
            temporary_wav.write_bytes(b"temporary")
            output = Path(directory) / "output.wav"
            with (
                patch.object(audiobook, "_synthesize_text_to_wav", return_value=(10, temporary_wav)) as synthesize,
                patch.object(audiobook, "save_generated_wav", return_value=output) as save,
                patch.object(audiobook, "_synthesize_text") as in_memory,
            ):
                result = create_audiobook(
                    backend=backend,
                    document_path=None,
                    pasted_text="word " * 2_000,
                    reference_audio=None,
                    settings=SynthesisSettings(),
                    ffmpeg_path=None,
                    ffprobe_path=None,
                    output_directory=directory,
                    output_format=".wav",
                )

            self.assertEqual(result.output_path, output)
            synthesize.assert_called_once()
            save.assert_called_once()
            in_memory.assert_not_called()
            self.assertFalse(temporary_wav.exists())

    def test_keep_abort_preserves_partial_wav_for_assembly(self):
        backend = FakeBackend()
        controller = GenerationController()
        controller.begin()

        def abort_after_first_chunk(request):
            controller.abort(True)
            return backend.synthesize(request)

        with self.assertRaises(audiobook._PartialGenerationCancelled) as raised:
            _synthesize_text_to_wav(
                backend,
                abort_after_first_chunk,
                "One. Two.",
                None,
                SynthesisSettings(max_chunk_chars=300),
                lambda _value, _message: None,
                0.0,
                1.0,
                controller,
            )
        try:
            samples, sample_rate = sf.read(raised.exception.path, dtype="float32")
            self.assertEqual(sample_rate, 10)
            self.assertEqual(len(samples), 2)
        finally:
            raised.exception.path.unlink(missing_ok=True)
            controller.finish()

    def test_document_wavs_are_deleted_after_assembly(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "section.wav"
            generated.write_bytes(b"temporary")

            with (
                patch.object(audiobook, "prepare_entire_document", return_value=["section"]),
                patch.object(
                    audiobook,
                    "document_generation_groups",
                    return_value=[{
                        "title": "Page 1",
                        "is_bookmark": False,
                        "parts": [{"page_index": 1, "text": "One. Two."}],
                    }],
                ),
                patch.object(audiobook, "table_of_contents_section_ids", return_value=[]),
                patch.object(audiobook, "_synthesize_parts_to_wav", return_value=(10, generated)),
                patch.object(audiobook, "create_batch_item", return_value={}),
                patch.object(
                    audiobook, "assemble_document_chapters", return_value=Path(directory) / "book.m4b"
                ) as assemble,
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
            self.assertEqual(assemble.call_args.args[1], 500)
            self.assertFalse(generated.exists())

    def test_document_wavs_are_retained_when_assembly_fails(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "section.wav"
            generated.write_bytes(b"temporary")
            with (
                patch.object(audiobook, "prepare_entire_document", return_value=["section"]),
                patch.object(
                    audiobook,
                    "document_generation_groups",
                    return_value=[{
                        "title": "Page 1",
                        "is_bookmark": False,
                        "parts": [{"page_index": 1, "text": "One."}],
                    }],
                ),
                patch.object(audiobook, "table_of_contents_section_ids", return_value=[]),
                patch.object(audiobook, "_synthesize_parts_to_wav", return_value=(10, generated)),
                patch.object(audiobook, "create_batch_item", return_value={}),
                patch.object(
                    audiobook, "assemble_document_chapters", side_effect=VoxBenchError("FFmpeg failed")
                ),
            ):
                with self.assertRaisesRegex(VoxBenchError, "FFmpeg failed"):
                    create_audiobook(
                        backend=backend,
                        document_path=None,
                        pasted_text=None,
                        reference_audio=None,
                        settings=SynthesisSettings(),
                        ffmpeg_path="ffmpeg",
                        ffprobe_path="ffprobe",
                        output_directory=directory,
                        document_id="test_document",
                    )
            retained = list((Path(directory) / "incomplete").glob("*.wav"))
            self.assertEqual(len(retained), 1)
            self.assertFalse(generated.exists())

    def test_document_page_progress_uses_page_labels(self):
        backend = FakeBackend()
        updates = []
        sample_rate, target = _synthesize_parts_to_wav(
            backend,
            backend.synthesize,
            [("One. Two.", 0.0, 0.5, "Generating page 1 of 2", None)],
            None,
            SynthesisSettings(max_chunk_chars=8),
            lambda value, message: updates.append((value, message)),
        )
        try:
            self.assertEqual(sample_rate, 10)
            self.assertTrue(any(message == "Generating page 1 of 2" for _, message in updates))
        finally:
            target.unlink(missing_ok=True)

    def test_blank_document_parts_are_skipped(self):
        backend = FakeBackend()
        sample_rate, target = _synthesize_parts_to_wav(
            backend,
            backend.synthesize,
            [
                ("Chapter 1: Opening", 0.0, 0.0, None, None),
                ("   ", 0.0, 1.0, "Generating page 1 of 1", 1000),
            ],
            None,
            SynthesisSettings(),
            lambda _value, _message: None,
        )
        try:
            self.assertEqual(sample_rate, 10)
            self.assertEqual(len(backend.requests), 1)
        finally:
            target.unlink(missing_ok=True)

    def test_bookmark_chapter_pauses_are_written_to_its_wav(self):
        backend = FakeBackend()
        sample_rate, target = _synthesize_parts_to_wav(
            backend,
            backend.synthesize,
            [
                ("Title", 0.0, 0.0, None, None),
                ("Page", 0.0, 1.0, None, 1000),
            ],
            None,
            SynthesisSettings(max_chunk_chars=300, pause_ms=250),
            lambda _value, _message: None,
            end_silence_ms=2000,
        )
        try:
            samples, written_rate = sf.read(target, dtype="float32")
            self.assertEqual(sample_rate, written_rate)
            self.assertEqual(len(samples), 4 + 10 + 20)
            self.assertTrue(np.allclose(samples[2:12], 0.0))
            self.assertTrue(np.allclose(samples[-20:], 0.0))
        finally:
            target.unlink(missing_ok=True)

    def test_bookmark_chapters_get_titles_and_embedded_pauses(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "chapter.wav"
            generated.write_bytes(b"temporary")
            with (
                patch.object(audiobook, "prepare_entire_document", return_value=["section"]),
                patch.object(
                    audiobook,
                    "document_generation_groups",
                    return_value=[{
                        "title": "Opening",
                        "is_bookmark": True,
                        "parts": [{"page_index": 1, "text": "Chapter text."}],
                    }],
                ),
                patch.object(audiobook, "table_of_contents_section_ids", return_value=[]),
                patch.object(audiobook, "_synthesize_parts_to_wav", return_value=(10, generated)) as synthesize,
                patch.object(audiobook, "create_batch_item", return_value={}),
                patch.object(
                    audiobook, "assemble_document_chapters", return_value=Path(directory) / "book.m4b"
                ) as assemble,
                patch.object(audiobook, "clear_document_audio_paths"),
            ):
                create_audiobook(
                    backend=backend,
                    document_path=None,
                    pasted_text=None,
                    reference_audio=None,
                    settings=SynthesisSettings(),
                    ffmpeg_path="ffmpeg",
                    ffprobe_path="ffprobe",
                    output_directory=directory,
                    document_id="test_document",
                )

            parts = synthesize.call_args.args[2]
            self.assertEqual(parts[0][0], "Chapter 1: Opening")
            self.assertEqual(parts[1][4], 1000)
            self.assertEqual(synthesize.call_args.kwargs["end_silence_ms"], 2000)
            self.assertEqual(assemble.call_args.args[1], 0)


if __name__ == "__main__":
    unittest.main()
