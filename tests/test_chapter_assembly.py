import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webui.chapter_assembly import (
    assemble_chapters,
    chapter_timeline,
    create_batch_item,
    ffmetadata_text,
    list_folder,
    move_batch_item,
    remove_batch_item,
    select_folder_dialog,
    update_batch_item,
)


class ChapterAssemblyTests(unittest.TestCase):
    def test_timeline_accounts_for_silence_and_crossfade(self):
        batch = [
            {
                "duration_ms": 2000,
                "trim_start_ms": 100,
                "trim_end_ms": 100,
            },
            {
                "duration_ms": 3000,
                "trim_start_ms": 0,
                "trim_end_ms": 0,
            },
        ]
        self.assertEqual(
            chapter_timeline(batch, "Silence", 500),
            ([(0, 2300), (2300, 5300)], 5300),
        )
        self.assertEqual(
            chapter_timeline(batch, "Crossfade", 500),
            ([(0, 1300), (1300, 4300)], 4300),
        )

    def test_batch_edits_reorder_and_remove_are_non_destructive(self):
        original = [
            {
                "name": "one.wav",
                "duration_ms": 2000,
                "volume_db": 0.0,
                "equalize": False,
                "trim_start_ms": 0,
                "trim_end_ms": 0,
            },
            {
                "name": "two.wav",
                "duration_ms": 2000,
                "volume_db": 0.0,
                "equalize": False,
                "trim_start_ms": 0,
                "trim_end_ms": 0,
            },
        ]
        edited = update_batch_item(original, 0, -3, True, 100, 200)
        self.assertEqual(original[0]["volume_db"], 0.0)
        self.assertEqual(edited[0]["volume_db"], -3)
        moved, selected = move_batch_item(edited, 0, 1)
        self.assertEqual((moved[1]["name"], selected), ("one.wav", 1))
        remaining, selected = remove_batch_item(moved, 1)
        self.assertEqual((len(remaining), selected), (1, 0))

    def test_metadata_has_sequential_chapter_names(self):
        metadata = ffmetadata_text([(0, 1000), (1000, 2500)])
        self.assertIn("title=Chapter 1", metadata)
        self.assertIn("title=Chapter 2", metadata)

    def test_folder_listing_only_contains_supported_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "notes.txt").write_text("ignored", encoding="utf-8")
            (root / "voice.wav").write_bytes(b"not decoded while listing")
            resolved, rows = list_folder(root)
            self.assertEqual(resolved, str(root.resolve()))
            self.assertEqual(rows, [[False, "voice.wav"]])

    def test_windows_folder_picker_uses_powershell_without_tkinter(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=directory.encode("utf-8"),
                stderr=b"",
            )
            with (
                patch("webui.chapter_assembly.sys.platform", "win32"),
                patch(
                    "webui.chapter_assembly.run_command",
                    return_value=completed,
                ) as command,
            ):
                selected = select_folder_dialog(directory)
            self.assertEqual(selected, str(Path(directory).resolve()))
            self.assertEqual(command.call_args.args[0][0], "powershell.exe")
            self.assertIn("-STA", command.call_args.args[0])

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "FFmpeg and FFprobe are required",
    )
    def test_m4b_export_embeds_chapters(self):
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for index, frequency in enumerate((440, 660), start=1):
                source = root / f"source_{index}.wav"
                subprocess.run(
                    [
                        ffmpeg,
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"sine=frequency={frequency}:duration=0.5",
                        "-y",
                        str(source),
                    ],
                    check=True,
                )
                sources.append(source)

            batch = [
                create_batch_item(str(source), ffprobe)
                for source in sources
            ]
            target = assemble_chapters(
                batch,
                "Silence",
                100,
                0,
                False,
                ".m4b",
                str(root),
                ffmpeg,
            )
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_chapters",
                    "-of",
                    "default=nw=1:nk=1",
                    str(target),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Chapter 1", result.stdout)
            self.assertIn("Chapter 2", result.stdout)


if __name__ == "__main__":
    unittest.main()
