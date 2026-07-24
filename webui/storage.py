import filecmp
import re
import shutil
import unicodedata
from pathlib import Path

import gradio as gr

from webui.config import (
    AUDIO_FILE_EXTENSIONS,
    MAX_TEXT_FILE_BYTES,
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
