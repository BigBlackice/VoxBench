from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
MODEL_CACHE_DIR = PROJECT_DIR / ".cache" / "huggingface"
SAMPLES_DIR = PROJECT_DIR / "samples"
OUTPUTS_DIR = PROJECT_DIR / "outputs"

EVENT_TAGS = [
    "[clear throat]",
    "[sigh]",
    "[shush]",
    "[cough]",
    "[groan]",
    "[sniff]",
    "[gasp]",
    "[chuckle]",
    "[laugh]",
]

TEXT_FILE_EXTENSIONS = {".txt", ".text", ".md"}
MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024
AUDIO_FILE_EXTENSIONS = {".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}
OUTPUT_FORMATS = (".wav", ".mp3", ".m4a", ".ogg", ".webm")
FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html"


def read_asset(filename: str) -> str:
    return (ASSETS_DIR / filename).read_text(encoding="utf-8")
