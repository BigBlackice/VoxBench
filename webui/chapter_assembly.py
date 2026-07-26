import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr

from webui.config import AUDIO_FILE_EXTENSIONS, OUTPUTS_DIR, PROJECT_DIR
from webui.storage import resolve_output_directory


ASSEMBLY_FORMATS = (".m4b", ".mp3", ".wav")
SPEECH_EQUALIZER_FILTER = (
    "highpass=f=80,"
    "equalizer=f=3000:t=q:w=0.8:g=2,"
    "lowpass=f=16000"
)


def run_command(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


def audio_duration_ms(file_path: str, ffprobe_path: str) -> int:
    """Return the duration of an audio file in milliseconds."""
    result = run_command(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            file_path,
        ]
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise gr.Error(f"Could not inspect audio file: {detail}")

    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise gr.Error("Could not determine the audio duration.") from error
    return max(0, round(duration * 1000))


def validate_audio_path(file_path: str | Path) -> Path:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in AUDIO_FILE_EXTENSIONS:
        raise gr.Error("Select a supported audio file.")
    return path


def list_folder(
    folder: str | Path,
    selected_paths: set[str] | None = None,
) -> tuple[str, list[list[Any]]]:
    """List only supported audio files in the selected folder."""
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        raise gr.Error("Folder not found.")

    selected_paths = selected_paths or set()
    rows: list[list[Any]] = []
    try:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name.casefold())
    except OSError as error:
        raise gr.Error(f"Could not open folder: {error}") from error

    for entry in entries:
        try:
            if entry.is_file() and entry.suffix.lower() in AUDIO_FILE_EXTENSIONS:
                resolved = str(entry.resolve())
                rows.append([resolved in selected_paths, entry.name])
        except OSError:
            continue
    return str(path), rows


def select_folder_dialog(initial_directory: str | Path) -> str | None:
    """Open the operating system's folder picker without Python GUI packages."""
    initial = str(Path(initial_directory).expanduser().resolve())

    if sys.platform == "win32":
        escaped_initial = initial.replace("'", "''")
        script = (
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();"
            "$shell=New-Object -ComObject Shell.Application;"
            "$folder=$shell.BrowseForFolder("
            f"0,'Select audio folder',0,'{escaped_initial}');"
            "if($folder){$folder.Self.Path}"
        )
        command = [
            "powershell.exe",
            "-NoProfile",
            "-STA",
            "-Command",
            script,
        ]
    elif sys.platform == "darwin":
        escaped_initial = initial.replace("\\", "\\\\").replace('"', '\\"')
        command = [
            "osascript",
            "-e",
            (
                'POSIX path of (choose folder with prompt "Select audio folder" '
                f'default location POSIX file "{escaped_initial}")'
            ),
        ]
    elif shutil.which("zenity"):
        command = [
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Select audio folder",
            f"--filename={initial}/",
        ]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory", initial]
    else:
        raise gr.Error(
            "No native folder picker was found. Enter or paste a folder path instead."
        )

    result = run_command(command)
    if result.returncode:
        # Native folder pickers commonly use a nonzero result when cancelled.
        return None
    selected = result.stdout.decode("utf-8", errors="replace").strip()
    if not selected:
        return None
    path = Path(selected).expanduser().resolve()
    if not path.is_dir():
        raise gr.Error("The selected folder could not be opened.")
    return str(path)


def create_batch_item(file_path: str, ffprobe_path: str) -> dict[str, Any]:
    path = validate_audio_path(file_path)
    return {
        "path": str(path),
        "name": path.name,
        "duration_ms": audio_duration_ms(str(path), ffprobe_path),
        "volume_db": 0.0,
        "equalize": False,
        "trim_start_ms": 0,
        "trim_end_ms": 0,
    }


def batch_rows(batch: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            f"Chapter {index}",
            item["name"],
            round(item["duration_ms"] / 1000, 2),
            item["volume_db"],
            "Yes" if item["equalize"] else "No",
            item["trim_start_ms"],
            item["trim_end_ms"],
        ]
        for index, item in enumerate(batch, start=1)
    ]


def sync_browser_selection(
    rows: list[list[Any]] | None,
    folder: str | Path,
    batch: list[dict[str, Any]] | None,
    ffprobe_path: str,
) -> list[dict[str, Any]]:
    """Synchronize browser checkboxes with the ordered assembly batch."""
    batch = list(batch or [])
    rows = rows or []
    folder = Path(folder).expanduser().resolve()
    visible_audio = {
        str((folder / str(row[1])).resolve()): bool(row[0])
        for row in rows
        if len(row) >= 2
        and (folder / str(row[1])).suffix.lower() in AUDIO_FILE_EXTENSIONS
    }

    batch = [
        item
        for item in batch
        if str(Path(item["path"]).resolve()) not in visible_audio
        or visible_audio[str(Path(item["path"]).resolve())]
    ]
    existing = {str(Path(item["path"]).resolve()) for item in batch}
    for path, checked in visible_audio.items():
        if checked and path not in existing:
            batch.append(create_batch_item(path, ffprobe_path))
            existing.add(path)
    return batch


def update_batch_item(
    batch: list[dict[str, Any]],
    index: int,
    volume_db: float,
    equalize: bool,
    trim_start_ms: int,
    trim_end_ms: int,
) -> list[dict[str, Any]]:
    if not batch or index < 0 or index >= len(batch):
        raise gr.Error("Select a chapter from the batch first.")

    updated = [dict(item) for item in batch]
    item = updated[index]
    trim_start_ms = max(0, int(trim_start_ms))
    trim_end_ms = max(0, int(trim_end_ms))
    if trim_start_ms + trim_end_ms >= item["duration_ms"]:
        raise gr.Error("Trimming must leave some audio in the chapter.")

    item.update(
        volume_db=float(volume_db),
        equalize=bool(equalize),
        trim_start_ms=trim_start_ms,
        trim_end_ms=trim_end_ms,
    )
    return updated


def move_batch_item(
    batch: list[dict[str, Any]],
    index: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    if not batch or index < 0 or index >= len(batch):
        raise gr.Error("Select a chapter from the batch first.")
    target = min(max(index + offset, 0), len(batch) - 1)
    updated = list(batch)
    updated[index], updated[target] = updated[target], updated[index]
    return updated, target


def remove_batch_item(
    batch: list[dict[str, Any]],
    index: int,
) -> tuple[list[dict[str, Any]], int]:
    if not batch or index < 0 or index >= len(batch):
        raise gr.Error("Select a chapter from the batch first.")
    updated = list(batch)
    updated.pop(index)
    return updated, min(index, len(updated) - 1)


def audio_filter(
    item: dict[str, Any],
    batch_volume_db: float = 0.0,
    batch_equalize: bool = False,
) -> str:
    duration_seconds = item["duration_ms"] / 1000
    start_seconds = item["trim_start_ms"] / 1000
    end_seconds = (item["duration_ms"] - item["trim_end_ms"]) / 1000
    filters = [
        f"atrim=start={start_seconds:.6f}:end={end_seconds:.6f}",
        "asetpts=PTS-STARTPTS",
    ]
    volume_db = float(item["volume_db"]) + float(batch_volume_db)
    if volume_db:
        filters.append(f"volume={volume_db:.3f}dB")
    if item["equalize"] or batch_equalize:
        filters.append(SPEECH_EQUALIZER_FILTER)
    filters.extend(
        [
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
        ]
    )
    return ",".join(filters)


def preview_processed_audio(
    file_path: str,
    volume_db: float,
    equalize: bool,
    trim_start_ms: int,
    trim_end_ms: int,
    ffmpeg_path: str,
    ffprobe_path: str,
) -> str:
    """Create a temporary WAV preview with the requested non-destructive edits."""
    item = create_batch_item(file_path, ffprobe_path)
    item = update_batch_item(
        [item],
        0,
        volume_db,
        equalize,
        trim_start_ms,
        trim_end_ms,
    )[0]
    with tempfile.NamedTemporaryFile(
        prefix="chapter_preview_",
        suffix=".wav",
        delete=False,
    ) as temporary_file:
        target = Path(temporary_file.name)
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        item["path"],
        "-af",
        audio_filter(item),
        "-c:a",
        "pcm_s16le",
        "-y",
        str(target),
    ]
    result = run_command(command)
    if result.returncode:
        target.unlink(missing_ok=True)
        detail = result.stderr.decode(errors="replace").strip()
        raise gr.Error(f"Could not create preview: {detail}")
    return str(target)


def chapter_timeline(
    batch: list[dict[str, Any]],
    transition_mode: str,
    transition_ms: int,
) -> tuple[list[tuple[int, int]], int]:
    durations = [
        item["duration_ms"] - item["trim_start_ms"] - item["trim_end_ms"]
        for item in batch
    ]
    if any(duration <= 0 for duration in durations):
        raise gr.Error("Each chapter must contain audio after trimming.")

    interval = max(0, int(transition_ms))
    if transition_mode == "Crossfade" and len(durations) > 1:
        if interval >= min(durations):
            raise gr.Error("Crossfade must be shorter than every chapter.")
        starts = [0]
        for previous_duration in durations[:-1]:
            starts.append(starts[-1] + previous_duration - interval)
    else:
        starts = [0]
        for previous_duration in durations[:-1]:
            starts.append(starts[-1] + previous_duration + interval)

    total = starts[-1] + durations[-1]
    chapters = [
        (start, starts[index + 1] if index + 1 < len(starts) else total)
        for index, start in enumerate(starts)
    ]
    return chapters, total


def ffmetadata_text(chapters: list[tuple[int, int]]) -> str:
    lines = [";FFMETADATA1"]
    for index, (start, end) in enumerate(chapters, start=1):
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start}",
                f"END={end}",
                f"title=Chapter {index}",
            ]
        )
    return "\n".join(lines) + "\n"


def _output_codec(extension: str) -> list[str]:
    if extension == ".m4b":
        return ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    if extension == ".mp3":
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    if extension == ".wav":
        return ["-c:a", "pcm_s16le"]
    raise gr.Error("Unsupported assembly format.")


def assemble_chapters(
    batch: list[dict[str, Any]],
    transition_mode: str,
    transition_ms: int,
    batch_volume_db: float,
    batch_equalize: bool,
    output_format: str,
    output_directory: str | None,
    ffmpeg_path: str,
) -> Path:
    """Assemble chapters directly into a final file with chapter metadata."""
    if not batch:
        raise gr.Error("Select at least one audio file.")
    if output_format not in ASSEMBLY_FORMATS:
        raise gr.Error("Unsupported assembly format.")

    for item in batch:
        validate_audio_path(item["path"])
    chapters, _ = chapter_timeline(batch, transition_mode, transition_ms)

    output_dir = resolve_output_directory(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = output_dir / f"{timestamp}_assembled_chapters{output_format}"
    counter = 2
    while target.exists():
        target = output_dir / (
            f"{timestamp}_assembled_chapters_{counter}{output_format}"
        )
        counter += 1

    command = [ffmpeg_path, "-hide_banner", "-loglevel", "error"]
    for item in batch:
        command.extend(["-i", item["path"]])

    filter_parts = [
        (
            f"[{index}:a]"
            f"{audio_filter(item, batch_volume_db, batch_equalize)}"
            f"[a{index}]"
        )
        for index, item in enumerate(batch)
    ]
    interval_seconds = max(0, int(transition_ms)) / 1000
    if len(batch) == 1:
        final_label = "a0"
    elif transition_mode == "Crossfade" and interval_seconds:
        previous = "a0"
        for index in range(1, len(batch)):
            output = f"mix{index}"
            filter_parts.append(
                f"[{previous}][a{index}]acrossfade=d={interval_seconds:.6f}"
                f":c1=tri:c2=tri[{output}]"
            )
            previous = output
        final_label = previous
    else:
        concat_inputs: list[str] = []
        for index in range(len(batch)):
            if index:
                silence_label = f"silence{index}"
                if interval_seconds:
                    filter_parts.append(
                        "anullsrc=r=48000:cl=stereo,"
                        f"atrim=duration={interval_seconds:.6f}"
                        f"[{silence_label}]"
                    )
                    concat_inputs.append(f"[{silence_label}]")
            concat_inputs.append(f"[a{index}]")
        final_label = "joined"
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}"
            f":v=0:a=1[{final_label}]"
        )

    with tempfile.NamedTemporaryFile(
        prefix="chapters_",
        suffix=".ffmeta",
        delete=False,
    ) as temporary_file:
        metadata_path = Path(temporary_file.name)
    try:
        metadata_path.write_text(ffmetadata_text(chapters), encoding="utf-8")
        metadata_input = len(batch)
        command.extend(
            [
                "-f",
                "ffmetadata",
                "-i",
                str(metadata_path),
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                f"[{final_label}]",
                "-map_metadata",
                str(metadata_input),
                *_output_codec(output_format),
                "-y",
                str(target),
            ]
        )
        result = run_command(command)
    finally:
        metadata_path.unlink(missing_ok=True)

    if result.returncode:
        target.unlink(missing_ok=True)
        detail = result.stderr.decode(errors="replace").strip()
        raise gr.Error(f"Could not assemble chapters: {detail}")
    return target


def initial_folder() -> str:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    return str(OUTPUTS_DIR)


def default_assembly_output() -> str:
    return str(OUTPUTS_DIR.relative_to(PROJECT_DIR)).replace("\\", "/") + "/"
