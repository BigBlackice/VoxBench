from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
MODEL_CACHE_DIR = PROJECT_DIR / ".cache" / "huggingface"

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


def read_asset(filename: str) -> str:
    return (ASSETS_DIR / filename).read_text(encoding="utf-8")
