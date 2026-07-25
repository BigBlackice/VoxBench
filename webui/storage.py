import filecmp
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

import gradio as gr
import soundfile as sf

from webui.config import (
    AUDIO_FILE_EXTENSIONS,
    MAX_TEXT_FILE_BYTES,
    OUTPUTS_DIR,
    PROJECT_DIR,
    SAMPLES_DIR,
    TEXT_FILE_EXTENSIONS,
)


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def load_text_file(file_path: str | None) -> str:
    """Read a dropped text file and return its contents for the prompt textbox."""
    if not file_path:
        return ""

    path = Path(file_path)
    if path.suffix.lower() not in TEXT_FILE_EXTENSIONS:
        raise gr.Error("Please upload a .txt, .text, or .md file.")

    data = path.read_bytes()
    if len(data) > MAX_TEXT_FILE_BYTES:
        raise gr.Error("Text files must be 5 MB or smaller.")

    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("cp1252")

    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise gr.Error("The text file encoding could not be recognized.")


def route_uploaded_file(
    file_path: str | None,
    samples_dir: Path = SAMPLES_DIR,
) -> tuple[str, str | Path | None]:
    """Classify and process a file from the shared text/audio drop target."""
    if not file_path:
        return "empty", None

    suffix = Path(file_path).suffix.lower()
    if suffix in TEXT_FILE_EXTENSIONS:
        return "text", load_text_file(file_path)
    if suffix in AUDIO_FILE_EXTENSIONS:
        return "audio", save_reference_sample(file_path, samples_dir)
    raise gr.Error("Please upload a supported text or audio file.")


def sanitize_sample_filename(filename: str) -> str:
    """Return a portable filename while retaining a supported audio extension."""
    path = Path(filename)
    suffix = path.suffix.lower()
    if suffix not in AUDIO_FILE_EXTENSIONS:
        raise gr.Error("Unsupported reference-audio file type.")

    stem = unicodedata.normalize("NFKC", path.stem)
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip(" ._-")
    stem = stem[:100] or "reference"
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"{stem}_sample"
    return f"{stem}{suffix}"


def list_reference_samples(
    samples_dir: Path = SAMPLES_DIR,
) -> list[tuple[str, str]]:
    """Return saved samples as display-name/path pairs for a Gradio dropdown."""
    if not samples_dir.is_dir():
        return []

    return [
        (path.name, str(path.resolve()))
        for path in sorted(samples_dir.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file() and path.suffix.lower() in AUDIO_FILE_EXTENSIONS
    ]


def save_reference_sample(
    file_path: str | None,
    samples_dir: Path = SAMPLES_DIR,
) -> Path | None:
    """Persist an uploaded reference clip without overwriting an existing file."""
    if not file_path:
        return None

    source = Path(file_path).resolve()
    if not source.is_file():
        raise gr.Error("The reference-audio file could not be found.")

    samples_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = samples_dir.resolve()
    filename = sanitize_sample_filename(source.name)
    target = samples_dir / filename

    try:
        if source.parent == samples_dir:
            return source
    except OSError:
        pass

    if target.exists() and filecmp.cmp(source, target, shallow=False):
        return target

    counter = 2
    while target.exists():
        target = samples_dir / f"{Path(filename).stem}_{counter}{Path(filename).suffix}"
        counter += 1

    shutil.copy2(source, target)
    return target


def resolve_output_directory(directory: str | None) -> Path:
    """Resolve a user-provided output directory relative to the project root."""
    if not directory or not directory.strip():
        return OUTPUTS_DIR

    path = Path(directory.strip()).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path.resolve()


def generated_audio_filename(text: str, created_at: datetime | None = None) -> str:
    """Create a readable filename from the generation time and prompt text."""
    created_at = created_at or datetime.now()
    prompt = re.sub(r"\[[^\]]+\]", "", text)
    prompt = unicodedata.normalize("NFKC", prompt)
    prompt = " ".join(prompt.split()[:5])
    prompt = re.sub(r"[^\w.-]+", "_", prompt, flags=re.UNICODE).strip(" ._-")
    prompt = prompt or "generated_audio"
    return f"{created_at:%Y%m%d_%H%M%S}_{prompt}.wav"


def save_generated_audio(
    audio,
    sample_rate: int,
    text: str,
    directory: str | None,
) -> Path:
    """Save generated audio as a collision-safe WAV file."""
    output_dir = resolve_output_directory(directory)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise gr.Error(f"Could not create output folder: {error}") from error

    filename = generated_audio_filename(text)
    target = output_dir / filename
    counter = 2
    while target.exists():
        target = output_dir / f"{Path(filename).stem}_{counter}.wav"
        counter += 1

    audio_data = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else audio
    try:
        sf.write(target, audio_data, sample_rate, format="WAV", subtype="PCM_16")
    except (OSError, RuntimeError) as error:
        raise gr.Error(f"Could not save generated audio: {error}") from error
    return target
