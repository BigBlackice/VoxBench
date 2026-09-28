import shutil
import uuid
from pathlib import Path

from webui.config import PROJECT_DIR
from webui.errors import VoxBenchError


UPLOAD_DIR = PROJECT_DIR / ".uploads"


def store_upload(name: str, content: bytes, suffixes: set[str]) -> Path:
    suffix = Path(name).suffix.lower()
    if suffix not in suffixes:
        raise VoxBenchError("Unsupported upload type.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)
    return target


def discard_upload(path: str | Path | None) -> None:
    if not path:
        return
    candidate = Path(path).resolve()
    try:
        if candidate.parent == UPLOAD_DIR.resolve():
            candidate.unlink(missing_ok=True)
    except OSError:
        pass


def clear_uploads() -> None:
    if UPLOAD_DIR.is_dir():
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
