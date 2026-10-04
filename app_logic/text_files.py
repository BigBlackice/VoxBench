"""Text-file loading and encoding detection for document input."""

from pathlib import Path

from webui.config import MAX_TEXT_FILE_BYTES, TEXT_FILE_EXTENSIONS
from webui.errors import VoxBenchError


def load_text_file(file_path: str | None) -> str:
    """Read a supported text file for narration input."""
    if not file_path:
        return ""
    path = Path(file_path)
    if path.suffix.lower() not in TEXT_FILE_EXTENSIONS:
        raise VoxBenchError("Please upload a .txt, .text, or .md file.")

    data = path.read_bytes()
    if len(data) > MAX_TEXT_FILE_BYTES:
        raise VoxBenchError("Text files must be 5 MB or smaller.")

    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("cp1252")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise VoxBenchError("The text file encoding could not be recognized.")
