from copy import deepcopy
from pathlib import Path
from typing import Any

from uvicorn.config import LOGGING_CONFIG


def build_log_config(project_dir: Path, component: str) -> dict[str, Any]:
    """Return Uvicorn logging with a bounded per-process VoxBench log file."""
    log_directory = project_dir / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    config = deepcopy(LOGGING_CONFIG)
    config["formatters"]["file"] = {
        "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
    }
    config["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "file",
        "filename": str(log_directory / f"{component}.log"),
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 3,
        "encoding": "utf-8",
    }
    config["loggers"]["uvicorn"]["handlers"].append("file")
    config["loggers"]["uvicorn.access"]["handlers"].append("file")
    config["root"] = {"handlers": ["default", "file"], "level": "INFO"}
    return config
